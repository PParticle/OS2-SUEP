"""
Debug test script - runs without TUI to see debug output
"""
from memory_model import PageManager

print("="*60)
print("Testing Multi-Process Initialization and Instruction Generation")
print("="*60)

# Test 1: Single process mode
print("\n### Test 1: Single Process Mode (Proc=1) ###")
mgr1 = PageManager(total_instructions=100, memory_blocks=4, mode="single", num_processes=1)
print(f"Total instructions generated: {len(mgr1.instructions)}")
print(f"First 10 instructions (should have pid=None):")
for i, inst in enumerate(mgr1.instructions[:10]):
    addr, op, pid = inst if len(inst) == 3 else (*inst, None)
    page = addr // 10
    print(f"  {i}: addr={addr}, page={page}, op={op}, pid={pid}")

# Test 2: Multi process mode
print("\n### Test 2: Multi Process Mode (Proc=5) ###")
mgr5 = PageManager(total_instructions=100, memory_blocks=4, mode="multi", num_processes=5)
print(f"Total instructions generated: {len(mgr5.instructions)}")

# Check uniqueness of (pid, page) combinations
pid_page_combinations = set()
for inst in mgr5.instructions[:100]:
    addr, op, pid = inst
    page = addr // 10
    pid_page_combinations.add((pid, page))

print(f"\nUnique (pid, page) combinations in first 100 instructions: {len(pid_page_combinations)}")
print(f"Expected: ~20 (5 processes × 4 pages)")
print(f"Actual combinations: {sorted(pid_page_combinations)[:20]}")

# Test 3: Run a few steps and check memory
print("\n### Test 3: Running simulation for 20 steps ###")
for step in range(20):
    result = mgr5.step()
    if result is None:
        break

print(f"\nFIFO Stats after 20 steps:")
print(f"  Total: {mgr5.algos['FIFO'].total_count}")
print(f"  Misses: {mgr5.algos['FIFO'].miss_count}")
print(f"  Miss Rate: {mgr5.algos['FIFO'].miss_count / mgr5.algos['FIFO'].total_count * 100:.1f}%")

print(f"\nMemory state (FIFO):")
for i, frame in enumerate(mgr5.algos['FIFO'].memory):
    if frame:
        print(f"  Frame {i}: pid={frame.get('pid')}, page={frame['page']}")
    else:
        print(f"  Frame {i}: Empty")
