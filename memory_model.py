import random

class AlgoState:
    """单个算法的独立状态机"""
    def __init__(self, name, memory_blocks):
        self.name = name
        self.memory_blocks = memory_blocks
        self.memory = [None] * memory_blocks
        
        # 统计数据
        self.miss_count = 0
        self.total_count = 0
        self.write_back_count = 0
        
        # 辅助变量
        self.load_counter = 0   # FIFO
        self.clock_hand = 0     # Clock
        
    def process(self, page_id, op_type, current_time, future_pages=None, pid=None):
        """
        处理一次内存访问
        支持多进程：pid参数用于标识页面所属进程
        """
        self.total_count += 1

         # 1. 查找页面（多进程模式下需同时匹配page和pid）
        hit_idx = -1
        for i, frame in enumerate(self.memory):
            if frame is not None and frame['page'] == page_id:
                # 单进程模式：pid为None，直接匹配；多进程模式：需同时匹配pid
                if pid is None or frame.get('pid') == pid:
                    hit_idx = i
                    break

        if hit_idx != -1:
            return self._handle_hit(hit_idx, op_type, current_time, pid)
        else:
            return self._handle_miss(page_id, op_type, current_time, future_pages, pid)
    
    def _handle_hit(self, idx, op_type, current_time, pid=None):
        """处理命中逻辑"""
        frame = self.memory[idx]
        frame['last_access'] = current_time

        # 算法特定行为
        if self.name == "LINUX":
            frame['ref_bit'] = 1
        elif self.name == "LINUX_NG":
            if not frame.get('is_active_list', False):
                frame['is_active_list'] = True
            self._balance_lists()

        # 脏页标记
        if op_type == 'W':
            frame['dirty'] = True

        return {"status": "Hit", "swapped": None, "swapped_pid": None, "is_write_back": False}

    def _handle_miss(self, page_id, op_type, current_time, future_pages, pid=None):
        """处理缺页逻辑"""
        self.miss_count += 1
        self.load_counter += 1
        is_write_back = False
        swapped_out = None
        swapped_pid = None

        # 创建新页帧（包含进程ID）
        new_frame = {
            "page": page_id,
            "pid": pid,  # 新增：进程ID（单进程模式下为None）
            "loaded_at": self.load_counter,
            "last_access": current_time,
            "ref_bit": 1,
            "dirty": (op_type == 'W'),
            "is_active_list": False # 默认为 Inactive
        }

        # 1. 尝试寻找空闲位
        target_idx = -1
        for i in range(self.memory_blocks):
            if self.memory[i] is None:
                target_idx = i
                break

        # 2. 如果没空位，执行置换
        if target_idx == -1:
            target_idx = self._get_victim(future_pages)
            victim_frame = self.memory[target_idx]
            swapped_out = victim_frame['page']
            swapped_pid = victim_frame.get('pid')  # 记录被换出页面的进程ID

            if victim_frame.get('dirty', False):
                self.write_back_count += 1
                is_write_back = True

        # 3. 装入新页
        self.memory[target_idx] = new_frame

        # Linux Clock 算法特殊处理：装入后指针下移
        if self.name == "LINUX":
            self.clock_hand = (target_idx + 1) % self.memory_blocks

        return {"status": "Miss", "swapped": swapped_out, "swapped_pid": swapped_pid, "is_write_back": is_write_back}

    def _balance_lists(self):
        """[LINUX_NG] 维护 Active/Inactive 列表平衡"""
        active_frames = [f for f in self.memory if f and f.get('is_active_list')]
        if len(active_frames) > self.memory_blocks // 2:
            victim = min(active_frames,key = lambda x:x['last_access'])
            victim['is_active_list'] = False

    def _get_victim(self, future_pages=None):
        valid_frames = [f for f in self.memory if f is not None]
        if not valid_frames: return 0

        if self.name == "FIFO":
            victim = min(valid_frames, key=lambda x: x['loaded_at'])
            return self.memory.index(victim)
        
        elif self.name == "LRU":
            victim = min(valid_frames, key=lambda x: x['last_access'])
            return self.memory.index(victim)
        
        elif self.name == "OPT":
            return self._get_opt_victim(future_pages)
        elif self.name == "LINUX":
           return self._run_clock_algorithm()
        elif self.name == "LINUX_NG":
            # 优先淘汰 Inactive，若无则淘汰全局 LRU
            inactive = [f for f in valid_frames if not f.get('is_active_list', False)]
            pool = inactive if inactive else valid_frames
            victim = min(pool, key=lambda x: x['last_access'])
            return self.memory.index(victim)
        
        return 0

    def _get_opt_victim(self, future_pages):
        """OPT 算法专用逻辑"""
        if future_pages is None: return 0
        max_dist = -1
        victim_idx = -1
        for i, frame in enumerate(self.memory):
            try:
                dist = future_pages.index(frame['page'])
            except ValueError:
                dist = 99999
            if dist > max_dist:
                max_dist = dist
                victim_idx = i
        return victim_idx

    def _run_clock_algorithm(self, dry_run=False):
        """Clock 算法核心逻辑 (支持 dry_run 用于预测)"""
        temp_hand = self.clock_hand
        # 防止死循环：最多遍历 2 圈 + 1
        for _ in range(self.memory_blocks * 2 + 1):
            frame = self.memory[temp_hand]
            if frame['ref_bit'] == 1:
                if not dry_run: frame['ref_bit'] = 0
                temp_hand = (temp_hand + 1) % self.memory_blocks
            else:
                victim_idx = temp_hand
                if not dry_run:
                    self.clock_hand = (temp_hand + 1) % self.memory_blocks
                return victim_idx
        return temp_hand

    def predict_next_victim(self, future_pages=None):
        """预测下一个受害者"""
        if None in self.memory: return -1
        
        if self.name == "LINUX":
            temp_hand = self.clock_hand
            for _ in range(self.memory_blocks * 2):
                if self.memory[temp_hand]['ref_bit'] == 0:
                    return temp_hand
                temp_hand = (temp_hand + 1) % self.memory_blocks
            return temp_hand
        else:
            return self._get_victim(future_pages)

    def get_snapshot(self, current_time):
        """
        生成用于 UI 显示的快照数据
        将“如何显示数据”的逻辑内聚在 Model 内部
        """
        snapshot = []
        for i, f in enumerate(self.memory):
            if f is None:
                snapshot.append(None)
                continue
                
            # 生成元数据文本
            meta = ""
            if self.name == "FIFO": 
                meta = f"SEQ:{f['loaded_at']}"
            elif self.name == "LRU": 
                meta = f"IDLE:{current_time - f['last_access']}"
            elif self.name == "LINUX": 
                meta = f"REF:{f['ref_bit']}"
            elif self.name == "LINUX_NG":
                list_name = "ACT" if f.get('is_active_list') else "INA"
                meta = f"{list_name}:{current_time - f['last_access']}"
            elif self.name == "OPT": 
                meta = "OPT"
            
            # 脏页覆盖显示
            if f.get('dirty'): meta = "DIRTY"
            
            snapshot.append({
                "page": f['page'],
                "pid": f.get('pid'),  # 新增：包含进程ID
                "meta": meta,
                "is_hand": (self.name == "LINUX" and i == self.clock_hand),
                "is_dirty": f.get('dirty', False),
                "is_active_list": f.get('is_active_list', False)
            })
        return snapshot

class PageManager:
    """总控制器：管理指令流和多算法状态"""
    def __init__(self, total_instructions=2000, total_pages=32, memory_blocks=4, mode="single", num_processes=1):
        self.total_instructions = total_instructions
        self.memory_blocks = memory_blocks
        self.total_pages = total_pages
        self.mode = mode  # "single" 或 "multi"
        self.num_processes = num_processes if mode == "multi" else 1
        self.process_info = {}  # 进程信息

        if self.mode == "multi":
            self._initialize_processes()

        self.algos = {
            name: AlgoState(name, memory_blocks)
            for name in ["FIFO", "LRU", "OPT", "LINUX", "LINUX_NG"]
        }
        self.reset()

    def _initialize_processes(self):
        """初始化多进程元数据"""
        colors = ["#89b4fa", "#a6e3a1", "#f9e2af", "#f38ba8", "#cba6f7"]
        for i in range(self.num_processes):
            self.process_info[i] = {
                "name": f"P{i}",
                "color": colors[i % len(colors)],
                "hot_range": (i * 40, (i + 1) * 40),
                "cold_range": (200 + i * 50, 250 + i * 50)
            }

    def _generate_process_sequence(self, hot_range, cold_range, length):
        """为单个进程生成指令序列（具有局部性）"""
        insts = []
        for _ in range(length):
            if random.random() < 0.8:
                page = random.randint(hot_range[0], hot_range[1] - 1)
                op = 'W' if random.random() < 0.5 else 'R'
            else:
                page = random.randint(cold_range[0], cold_range[1] - 1)
                op = 'W' if random.random() < 0.1 else 'R'
            insts.append((page * 10, op))
        return insts

    def _interleave_sequences(self, process_sequences):
        """使用轮转调度交错多个进程的指令序列"""
        result = []
        burst_size = 5  # 每个进程连续执行5条指令
        pid_order = list(range(self.num_processes))

        max_length = max(len(seq) for seq in process_sequences.values())

        for cycle in range(0, max_length, burst_size):
            for pid in pid_order:
                sequence = process_sequences[pid]
                start = cycle
                end = min(cycle + burst_size, len(sequence))
                for addr, op in sequence[start:end]:
                    result.append((addr, op, pid))  # 指令元组包含pid

        return result

    def _generate_multi_process_instructions(self):
        """生成多进程交错指令序列"""
        process_sequences = {}
        for pid in range(self.num_processes):
            hot_range = self.process_info[pid]["hot_range"]
            cold_range = self.process_info[pid]["cold_range"]
            # 修改：每个进程至少执行800条指令，确保工作集充分竞争
            # 单进程：2000条；多进程：每进程800-2000条（取决于进程数）
            length = max(800, self.total_instructions // self.num_processes)
            process_sequences[pid] = self._generate_process_sequence(
                hot_range, cold_range, length
            )
        return self._interleave_sequences(process_sequences)

    def _generate_instructions(self):
        """根据模式生成指令序列"""
        if self.mode == "multi":
            return self._generate_multi_process_instructions()
        else:
            # 单进程模式：原有逻辑
            insts = []
            for _ in range(self.total_instructions):
                rand_val = random.random()
                if rand_val < 0.8:
                    hot_inst = random.randint(0, 39)
                    insts.append((hot_inst, 'W' if random.random() < 0.5 else 'R', None))
                else:
                    cold_inst = random.randint(40, 200)
                    insts.append((cold_inst, 'W' if random.random() < 0.1 else 'R', None))
            return insts[:self.total_instructions]

    def load_belady_sequence(self):
        """加载 Belady 异常经典序列"""
        self.mode = "BELADY"
        pages = [1, 2, 3, 4, 1, 2, 5, 1, 2, 3, 4, 5]
        self.instructions = [(p * 10, 'R', None) for p in pages]  # 添加None作为pid
        self.current_inst_idx = 0
        self.reset_algos()

    def step(self):
        """执行单步模拟（支持多进程）"""
        if self.current_inst_idx >= len(self.instructions):
            return None

        # 解包指令（包含pid）
        instruction = self.instructions[self.current_inst_idx]
        if len(instruction) == 3:
            addr, op_type, pid = instruction
        else:
            # 兼容旧格式（没有pid）
            addr, op_type = instruction
            pid = None

        page_id = addr // 10
        self.current_time += 1

        # 仅为 OPT 算法准备未来数据 (按需计算)
        future_pages = None

        step_results = {}
        for name, algo in self.algos.items():
            if name == "OPT" and future_pages is None:
                future_tuples = self.instructions[self.current_inst_idx+1:]
                future_pages = [x[0] // 10 for x in future_tuples]

            res = algo.process(page_id, op_type, self.current_time, future_pages, pid)
            miss_rate = (algo.miss_count / algo.total_count) * 100 if algo.total_count > 0 else 0
            step_results[name] = {
                "status": res["status"],
                "swapped": res["swapped"],
                "swapped_pid": res.get("swapped_pid"),  # 新增
                "is_write_back": res["is_write_back"],
                "miss_rate": miss_rate,
                "miss_count": algo.miss_count,
                "wb_count": algo.write_back_count
            }

        self.current_inst_idx += 1

        # 获取当前视图算法的 UI 数据
        view_algo = self.algos[self.view_algo_name]

        # 预测高亮 (同样按需计算)
        pred_future = future_pages if self.view_algo_name == "OPT" else None
        if self.view_algo_name == "OPT" and pred_future is None:
            future_tuples = self.instructions[self.current_inst_idx:]
            pred_future = [x[0] // 10 for x in future_tuples]

        next_victim = view_algo.predict_next_victim(pred_future)
        mem_view = view_algo.get_snapshot(self.current_time)

        return {
            "inst": addr,
            "op": op_type,
            "page": page_id,
            "pid": pid,  # 新增：返回进程ID
            "results": step_results,
            "view_algo": self.view_algo_name,
            "memory": mem_view,
            "next_victim": next_victim,
            "current_step": self.current_inst_idx
        }

    def reset(self):
        self.current_inst_idx = 0
        self.current_time = 0
        self.mode = "NORMAL"
        self.view_algo_name = "FIFO"
        self.instructions = self._generate_instructions()
        self.reset_algos()
        
    def reset_algos(self):
        for algo in self.algos.values():
            algo.__init__(algo.name, self.memory_blocks)