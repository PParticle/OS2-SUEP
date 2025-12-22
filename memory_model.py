import random

class AlgoState:
    """
    单个页面置换算法的状态机

    管理单个算法的内存块状态、统计数据和算法特定的辅助变量
    支持 FIFO、LRU、OPT、LINUX(Clock)、LINUX_NG 五种算法
    """
    def __init__(self, name, memory_blocks):
        self.name = name
        self.memory_blocks = memory_blocks
        self.memory = [None] * memory_blocks

        # 统计数据
        self.miss_count = 0
        self.total_count = 0
        self.write_back_count = 0

        # 算法辅助变量
        self.load_counter = 0   # FIFO 装入顺序计数器
        self.clock_hand = 0     # Clock 算法指针位置
        
    def process(self, page_id, op_type, current_time, future_pages=None, pid=None):
        """
        处理一次内存访问请求

        Args:
            page_id: 页面号
            op_type: 操作类型 ('R'读 / 'W'写)
            current_time: 当前时间戳
            future_pages: 未来页面访问序列 (仅 OPT 算法使用)
            pid: 进程ID (多进程模式下使用，单进程为 None)

        Returns:
            dict: 包含状态、被换出页面、是否写回等信息
        """
        self.total_count += 1

        # 查找页面：多进程模式下需同时匹配 (pid, page_id)
        hit_idx = -1
        for i, frame in enumerate(self.memory):
            if frame is not None and frame['page'] == page_id:
                # 单进程：pid 为 None 直接匹配；多进程：需匹配 pid
                if pid is None or frame.get('pid') == pid:
                    hit_idx = i
                    break

        if hit_idx != -1:
            return self._handle_hit(hit_idx, op_type, current_time, pid)
        else:
            return self._handle_miss(page_id, op_type, current_time, future_pages, pid)
    
    def _handle_hit(self, idx, op_type, current_time, pid=None):
        """处理页面命中"""
        frame = self.memory[idx]
        frame['last_access'] = current_time

        # 算法特定的命中处理
        if self.name == "LINUX":
            frame['ref_bit'] = 1
        elif self.name == "LINUX_NG":
            if not frame.get('is_active_list', False):
                frame['is_active_list'] = True
            self._balance_lists()

        # 写操作时标记脏页
        if op_type == 'W':
            frame['dirty'] = True

        return {"status": "Hit", "swapped": None, "swapped_pid": None, "is_write_back": False}

    def _handle_miss(self, page_id, op_type, current_time, future_pages, pid=None):
        """处理缺页中断"""
        self.miss_count += 1
        self.load_counter += 1
        is_write_back = False
        swapped_out = None
        swapped_pid = None

        # 创建新页帧
        new_frame = {
            "page": page_id,
            "pid": pid,
            "loaded_at": self.load_counter,
            "last_access": current_time,
            "ref_bit": 1,
            "dirty": (op_type == 'W'),
            "is_active_list": False  # LINUX_NG: 新页面默认放入 Inactive 列表
        }

        # 1. 查找空闲帧
        target_idx = -1
        for i in range(self.memory_blocks):
            if self.memory[i] is None:
                target_idx = i
                break

        # 2. 无空闲帧时执行页面置换
        if target_idx == -1:
            target_idx = self._get_victim(future_pages)
            victim_frame = self.memory[target_idx]
            if victim_frame:
                swapped_out = victim_frame['page']
                swapped_pid = victim_frame.get('pid')

                # 检查是否需要写回磁盘
                if victim_frame.get('dirty', False):
                    self.write_back_count += 1
                    is_write_back = True

        # 3. 装入新页面
        self.memory[target_idx] = new_frame

        # Clock 算法特殊处理：装入后指针下移
        if self.name == "LINUX":
            self.clock_hand = (target_idx + 1) % self.memory_blocks

        return {"status": "Miss", "swapped": swapped_out, "swapped_pid": swapped_pid, "is_write_back": is_write_back}

    def _balance_lists(self):
        """LINUX_NG: 维护 Active/Inactive 列表平衡"""
        active_frames = [f for f in self.memory if f and f.get('is_active_list')]
        if len(active_frames) > self.memory_blocks // 2:
            victim = min(active_frames, key=lambda x: x['last_access'])
            victim['is_active_list'] = False

    def _get_victim(self, future_pages=None):
        """选择要被置换的页面"""
        valid_frames = [f for f in self.memory if f is not None]
        if not valid_frames:
            return 0

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
            # 优先淘汰 Inactive 列表中的页面，若无则淘汰全局 LRU
            inactive = [f for f in valid_frames if not f.get('is_active_list', False)]
            pool = inactive if inactive else valid_frames
            victim = min(pool, key=lambda x: x['last_access'])
            return self.memory.index(victim)

        return 0

    def _get_opt_victim(self, future_pages):
        """OPT 算法：选择未来最晚使用的页面"""
        if future_pages is None:
            return 0
        max_dist = -1
        victim_idx = -1
        for i, frame in enumerate(self.memory):
            try:
                dist = future_pages.index(frame['page'])
            except ValueError:
                dist = 99999  # 未来不再使用
            if dist > max_dist:
                max_dist = dist
                victim_idx = i
        return victim_idx

    def _run_clock_algorithm(self, dry_run=False):
        """Clock 算法核心逻辑（支持 dry_run 用于预测）"""
        temp_hand = self.clock_hand
        # 防止死循环：最多遍历 2 圈 + 1
        for _ in range(self.memory_blocks * 2 + 1):
            frame = self.memory[temp_hand]
            if frame['ref_bit'] == 1:
                if not dry_run:
                    frame['ref_bit'] = 0
                temp_hand = (temp_hand + 1) % self.memory_blocks
            else:
                victim_idx = temp_hand
                if not dry_run:
                    self.clock_hand = (temp_hand + 1) % self.memory_blocks
                return victim_idx
        return temp_hand

    def predict_next_victim(self, future_pages=None):
        """预测下一个被置换的页面（用于 UI 高亮显示）"""
        if None in self.memory:
            return -1

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
        生成用于 UI 显示的内存快照

        根据算法类型生成不同的元数据信息，将数据展示逻辑封装在 Model 内部
        """
        snapshot = []
        for i, f in enumerate(self.memory):
            if f is None:
                snapshot.append(None)
                continue

            # 根据算法生成元数据文本
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

            # 脏页标记优先显示
            if f.get('dirty'):
                meta = "DIRTY"

            snapshot.append({
                "page": f['page'],
                "pid": f.get('pid'),
                "meta": meta,
                "is_hand": (self.name == "LINUX" and i == self.clock_hand),
                "is_dirty": f.get('dirty', False),
                "is_active_list": f.get('is_active_list', False)
            })
        return snapshot

class PageManager:
    """
    虚拟内存模拟器总控制器

    管理指令流生成、多进程调度和多算法并行运行
    支持单进程和多进程两种模式
    """
    def __init__(self, total_instructions=2000, total_pages=32, memory_blocks=4, mode="single", num_processes=1):
        self.total_instructions = total_instructions
        self.memory_blocks = memory_blocks
        self.total_pages = total_pages
        self.mode = mode  # "single" 或 "multi"
        self.num_processes = num_processes if mode == "multi" else 1
        self.process_info = {}  # 进程元数据

        if self.mode == "multi":
            self._initialize_processes()

        # 创建五种算法的并行状态机
        self.algos = {
            name: AlgoState(name, memory_blocks)
            for name in ["FIFO", "LRU", "OPT", "LINUX", "LINUX_NG"]
        }
        self.reset()

    def _initialize_processes(self):
        """
        初始化多进程元数据

        核心设计：所有进程使用相同的虚拟页面范围，模拟真实 OS 行为
        - 每个进程都有独立的虚拟地址空间
        - P0 的虚拟 Page 2 和 P1 的虚拟 Page 2 映射到不同的物理页
        - 通过 (pid, page) 组合唯一标识物理页
        """
        colors = ["#89b4fa", "#a6e3a1", "#f9e2af", "#f38ba8", "#cba6f7"]
        for i in range(self.num_processes):
            self.process_info[i] = {
                "name": f"P{i}",
                "color": colors[i % len(colors)],
                "hot_range": (0, 4),      # 所有进程都访问虚拟 Page 0-3
                "cold_range": (50, 60)    # 冷页面范围
            }

    def _generate_process_sequence(self, hot_range, cold_range, length):
        """
        为单个进程生成具有局部性的指令序列

        95% 概率访问热区页面，5% 访问冷区页面
        模拟真实程序的局部性原理
        """
        insts = []
        for _ in range(length):
            if random.random() < 0.95:
                # 热区访问
                page = random.randint(hot_range[0], hot_range[1] - 1)
                op = 'W' if random.random() < 0.5 else 'R'
            else:
                # 冷区访问
                page = random.randint(cold_range[0], cold_range[1] - 1)
                op = 'W' if random.random() < 0.1 else 'R'
            insts.append((page * 10, op))
        return insts

    def _interleave_sequences(self, process_sequences):
        """
        使用时间片轮转调度交错多个进程的指令序列

        每个进程连续执行 5 条指令后切换（模拟时间片）
        """
        result = []
        burst_size = 5
        pid_order = list(range(self.num_processes))

        max_length = max(len(seq) for seq in process_sequences.values())

        for cycle in range(0, max_length, burst_size):
            for pid in pid_order:
                sequence = process_sequences[pid]
                start = cycle
                end = min(cycle + burst_size, len(sequence))
                for addr, op in sequence[start:end]:
                    result.append((addr, op, pid))

        return result

    def _generate_multi_process_instructions(self):
        """生成多进程交错指令序列"""
        process_sequences = {}
        for pid in range(self.num_processes):
            hot_range = self.process_info[pid]["hot_range"]
            cold_range = self.process_info[pid]["cold_range"]
            # 每个进程至少执行 800 条指令
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
            # 单进程模式
            insts = []
            for _ in range(self.total_instructions):
                if random.random() < 0.95:
                    # 热区：Page 0-3（地址 0-39）
                    hot_inst = random.randint(0, 39)
                    insts.append((hot_inst, 'W' if random.random() < 0.5 else 'R', None))
                else:
                    # 冷区
                    cold_inst = random.randint(400, 600)
                    insts.append((cold_inst, 'W' if random.random() < 0.1 else 'R', None))
            return insts[:self.total_instructions]

    def load_belady_sequence(self):
        """加载 Belady 异常经典测试序列"""
        self.mode = "BELADY"
        pages = [1, 2, 3, 4, 1, 2, 5, 1, 2, 3, 4, 5]
        self.instructions = [(p * 10, 'R', None) for p in pages]
        self.current_inst_idx = 0
        self.reset_algos()

    def step(self):
        """
        执行单步模拟

        返回当前步骤的详细信息，包括所有算法的执行结果和内存快照
        """
        if self.current_inst_idx >= len(self.instructions):
            return None

        # 解包指令元组
        instruction = self.instructions[self.current_inst_idx]
        if len(instruction) == 3:
            addr, op_type, pid = instruction
        else:
            # 兼容旧格式
            addr, op_type = instruction
            pid = None

        page_id = addr // 10
        self.current_time += 1

        # 为 OPT 算法准备未来页面访问序列
        future_pages = None

        # 并行运行所有算法
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
                "swapped_pid": res.get("swapped_pid"),
                "is_write_back": res["is_write_back"],
                "miss_rate": miss_rate,
                "miss_count": algo.miss_count,
                "wb_count": algo.write_back_count
            }

        self.current_inst_idx += 1

        # 获取当前查看算法的内存快照和预测信息
        view_algo = self.algos[self.view_algo_name]

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
            "pid": pid,
            "results": step_results,
            "view_algo": self.view_algo_name,
            "memory": mem_view,
            "next_victim": next_victim,
            "current_step": self.current_inst_idx
        }

    def reset(self):
        """重置模拟状态（保留模式设置）"""
        self.current_inst_idx = 0
        self.current_time = 0
        # 保留 mode 设置，避免覆盖 multi/single
        self.view_algo_name = "FIFO"
        self.instructions = self._generate_instructions()
        self.reset_algos()

    def reset_algos(self):
        """重置所有算法的状态"""
        for algo in self.algos.values():
            algo.__init__(algo.name, self.memory_blocks)