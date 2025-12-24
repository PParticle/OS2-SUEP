import random

class AlgoState:

    def __init__(self, name, memory_blocks):
        self.name = name
        self.memory_blocks = memory_blocks #内存块大小
        self.memory = [None] * memory_blocks #内存块

        # 统计数据
        self.miss_count = 0
        self.total_count = 0
        self.write_back_count = 0

        # 算法辅助变量
        self.load_counter = 0   # FIFO 装入顺序计数器
        self.clock_hand = 0     # Clock 算法指针位置

    """处理一次内存访问请求"""
    def process(self, page_id, op_type, current_time, future_pages=None, pid=None):
        self.total_count += 1
        # 查找页面：多进程模式下需同时匹配 (pid, page_id)
        hit_idx = -1
        for i, frame in enumerate(self.memory):
            if frame is not None and frame['page'] == page_id:
                # 单进程：pid 为 None 直接匹配；多进程：需匹配 pid
                if pid is None or frame.get('pid') == pid:
                    hit_idx = i
                    break

        if hit_idx != -1:   #说明内存块已经存在该页
            return self._handle_hit(hit_idx, op_type, current_time, pid)
        else:
            return self._handle_miss(page_id, op_type, current_time, future_pages, pid)

    """处理页面命中"""
    def _handle_hit(self, idx, op_type, current_time, pid=None):
        frame = self.memory[idx]
        frame['last_access'] = current_time

        # 算法特定的命中处理
        if self.name == "LINUX":
            frame['ref_bit'] = 1
        elif self.name == "LINUX_NG":
            frame['is_active_list'] = True
            self._balance_lists()   #维护 Active/Inactive 列表平衡

        # 写操作时标记脏页
        if op_type == 'W':
            frame['dirty'] = True

        return {"status": "Hit", "swapped": None, "swapped_pid": None, "is_write_back": False}

    """处理缺页中断"""
    def _handle_miss(self, page_id, op_type, current_time, future_pages, pid=None):
        self.miss_count += 1
        self.load_counter += 1
        is_write_back = False
        swapped_out = None
        swapped_pid = None

        # 创建新页
        new_frame = {
            "page": page_id,
            "pid": pid,
            "loaded_at": self.load_counter,
            "last_access": current_time,
            "ref_bit": 1,
            "dirty": (op_type == 'W'),
            "is_active_list": False  # LINUX_NG: 新页面默认放入 Inactive 列表
        }

        # 查找空闲帧
        target_idx = -1
        for i in range(self.memory_blocks):
            if self.memory[i] is None:
                target_idx = i
                break

        # 无空闲帧时执行页面置换
        if target_idx == -1:
            target_idx = self._get_victim(future_pages)
            victim_frame = self.memory[target_idx]
            swapped_out = victim_frame['page']  #被交换的页号
            swapped_pid = victim_frame.get('pid')

            # 检查是否需要写回磁盘
            if victim_frame.get('dirty'):
                self.write_back_count += 1
                is_write_back = True

        # 3. 装入新页面
        self.memory[target_idx] = new_frame

        # Clock 算法特殊处理：装入后指针下移
        if self.name == "LINUX":
            self.clock_hand = (target_idx + 1) % self.memory_blocks

        return {"status": "Miss", "swapped": swapped_out, "swapped_pid": swapped_pid, "is_write_back": is_write_back}

    """LINUX_NG: 维护 Active/Inactive 列表平衡"""
    def _balance_lists(self):
        active_frames = [f for f in self.memory if f and f.get('is_active_list')]
        #如果活跃的页表大于内存大小的一半，则需要最早加入的页放入Inactive列表
        if len(active_frames) > self.memory_blocks // 2:
            victim = min(active_frames, key=lambda x: x['last_access'])
            victim['is_active_list'] = False

    """找被置换的页面的位置"""
    def _get_victim(self, future_pages=None):
        valid_frames = [f for f in self.memory if f is not None]

        # 先进先出
        if self.name == "FIFO":
            victim = min(valid_frames, key=lambda x: x['loaded_at'])
            return self.memory.index(victim)
        #最久未使用
        elif self.name == "LRU":
            victim = min(valid_frames, key=lambda x: x['last_access'])
            return self.memory.index(victim)
        #最优
        elif self.name == "OPT":
            return self._get_opt_victim(future_pages)

        elif self.name == "LINUX":
            return self._run_clock_algorithm()

        elif self.name == "LINUX_NG":
            inactive = [f for f in valid_frames if not f.get('is_active_list')]  # inactive列表
            pool = inactive if inactive else valid_frames   #inactive为空则进行LRU
            victim = min(pool, key=lambda x: x['last_access'])
            return self.memory.index(victim)

        return 0

    """OPT 算法：选择未来最晚使用的页面"""
    def _get_opt_victim(self, future_pages):
        if future_pages is None:
            return 0
        max_dist = -1   #在序列的位置
        victim_idx = -1 #内存块的位置
        for i, frame in enumerate(self.memory):
            try:
                #后续页面的最早位置
                dist = future_pages.index(frame['page'])
            except ValueError:
                dist = 99999  # 未来不再使用
            if dist > max_dist:
                max_dist = dist
                victim_idx = i
        return victim_idx

    """ Clock 算法：选择最近未用的页面"""
    def _run_clock_algorithm(self):
        temp_hand = self.clock_hand
        # 防止死循环：最多遍历 2 圈 + 1
        for _ in range(self.memory_blocks * 2 + 1):
            frame = self.memory[temp_hand]
            if frame['ref_bit'] == 1:
                frame['ref_bit'] = 0
                temp_hand = (temp_hand + 1) % self.memory_blocks
            else:
                victim_idx = temp_hand
                self.clock_hand = (temp_hand + 1) % self.memory_blocks
                return victim_idx
        return temp_hand

    """预测下一个被置换的页面"""
    def predict_next_victim(self, future_pages=None):
        if None in self.memory:
            return -1
        if self.name == "LINUX":    #防止改变内存的链表
            temp_hand = self.clock_hand
            for _ in range(self.memory_blocks * 2):
                if self.memory[temp_hand]['ref_bit'] == 0:
                    return temp_hand
                temp_hand = (temp_hand + 1) % self.memory_blocks
            return temp_hand
        else:
            return self._get_victim(future_pages)

    """特殊数据的展示"""
    def get_snapshot(self, current_time):
        snapshot = []
        for i, f in enumerate(self.memory):
            if f is None:
                snapshot.append(None)
                continue
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
                "is_dirty": f.get('dirty'),
                "is_active_list": f.get('is_active_list')
            })
        return snapshot

class PageManager:

    def __init__(self, total_instructions=2000, total_pages=32, memory_blocks=4, mode="single", num_processes=1):
        self.total_instructions = total_instructions  # 总指令数
        self.memory_blocks = memory_blocks  # 物理内存块数
        self.total_pages = total_pages  # 虚拟页面总数
        self.mode = mode  # "single" 或 "multi"
        self.num_processes = num_processes if mode == "multi" else 1 #进程数
        self.process_info = {}  # 进程字典，存放进程下的序列

        if self.mode == "multi":
            self._initialize_processes()

        # 并行五种算法
        self.algos = {
            name: AlgoState(name, memory_blocks)
            for name in ["FIFO", "LRU", "OPT", "LINUX", "LINUX_NG"]
        }
        self.reset()

    """开始模拟状态"""
    def reset(self):
        self.current_time = 0   #时间戳
        self.view_algo_name = "FIFO"
        self.instructions = self._generate_instructions()
        self.reset_algos()

    """重置所有算法的状态"""
    def reset_algos(self):
        for algo in self.algos.values():
            algo.__init__(algo.name, self.memory_blocks)

    """初始化多进程"""
    def _initialize_processes(self):
        colors = ["#89b4fa", "#a6e3a1", "#f9e2af", "#f38ba8", "#cba6f7"]
        for i in range(self.num_processes):
            self.process_info[i] = {
                "name": f"P{i}",
                "color": colors[i % len(colors)],
            }

    """为单个进程生成随机序列"""
    def _generate_process_sequence(self, hot_range, cold_range, length):
        insts = []
        # 为模拟真实程序的局部性原理95% 概率访问热区页面，5% 访问冷区页面
        for _ in range(length):
            if random.random() < 0.95:
                # 热区访问
                addr = random.randint(hot_range[0], hot_range[1] - 1)
                op = 'W' if random.random() < 0.5 else 'R'
            else:
                # 冷区访问
                addr = random.randint(cold_range[0], cold_range[1] - 1)
                op = 'W' if random.random() < 0.1 else 'R'
            insts.append((addr, op))
        return insts

    """模拟生成指令序列"""
    def _generate_instructions(self):
        if self.mode == "multi":
            process_sequences = {}  #接收生成的序列
            for pid in range(self.num_processes):
                hot_inst = [0, 40]
                cold_inst = [500, 600]
                # 每个进程至少执行 800 条指令
                length = max(800, self.total_instructions // self.num_processes)
                process_sequences[pid] = self._generate_process_sequence(hot_inst, cold_inst, length)
            #返回分组的序列
            return self._interleave_sequences(process_sequences)
        else:
            # 单进程模式
            hot_inst = [0, 40]
            cold_inst = [400, 600]
            return self._generate_process_sequence(hot_inst,cold_inst,self.total_instructions)

    """模拟时间片 每个进程连续执行 10 条指令后切换"""
    def _interleave_sequences(self, process_sequences):
        result = []
        burst_size = 10
        pid_order = list(range(self.num_processes))# pid链表
        # 最长的进程序列长度
        max_length = max(len(seq) for seq in process_sequences.values())
        # 以时间片为步长遍历最长序列
        for cycle in range(0, max_length, burst_size):
            for pid in pid_order:
                sequence = process_sequences[pid]
                start = cycle
                end = min(cycle + burst_size, len(sequence))#防止指针溢出
                for addr, op in sequence[start:end]:
                    result.append((addr, op, pid))
        return result   #最终的序列

    """返回当前步骤的详细信息，包括所有算法的执行结果和内存快照"""
    def step(self):
        #防止溢出
        if self.current_time >= len(self.instructions):
            return None
        instruction = self.instructions[self.current_time]  #获得当前指令
        #判断是否存在pid
        if len(instruction) == 3:
            addr, op_type, pid = instruction
        else:
            addr, op_type = instruction
            pid = None

        # 并行运行所有算法
        step_results = {}   #操作信息
        future_pages = None # 未来页序列
        page_id = addr // 10
        for name, algo in self.algos.items():
            if name == "OPT" and future_pages is None:
                future_tuples = self.instructions[self.current_time+1:]
                future_pages = [x[0] // 10 for x in future_tuples]

            #放入页
            res = algo.process(page_id, op_type, self.current_time, future_pages, pid)
            miss_rate = (algo.miss_count / algo.total_count) * 100 if algo.total_count > 0 else 0   #缺页率
            step_results[name] = {
                "status": res["status"],
                "swapped": res["swapped"],  #被交换的页号
                "swapped_pid": res.get("swapped_pid"),
                "is_write_back": res["is_write_back"],
                "miss_rate": miss_rate,
                "miss_count": algo.miss_count,
                "wb_count": algo.write_back_count
            }

        self.current_time += 1
        # 获取当前查看算法的内存快照和
        view_algo = self.algos[self.view_algo_name] #算法类
        pred_future = future_pages if self.view_algo_name == "OPT" else None
        #更新未来序列
        if self.view_algo_name == "OPT" and pred_future is None:
            future_tuples = self.instructions[self.current_time:]
            pred_future = [x[0] // 10 for x in future_tuples]
        #预测信息
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
            "current_step": self.current_time
        }

    """测试序列"""
    def load_belady_sequence(self):
        self.mode = "BELADY"
        pages = [1, 2, 3, 4, 1, 2, 5, 1, 2, 3, 4, 5]
        self.instructions = [(p * 10, 'R', None) for p in pages]
        self.current_time = 0
        self.reset_algos()