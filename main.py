"""
虚拟内存模拟器 - 主程序入口

支持五种页面置换算法的可视化模拟：
- FIFO (先进先出)
- LRU (最近最少使用)
- OPT (最佳置换)
- LINUX (Clock 算法)
- LINUX_NG (改进的 Linux 算法，Active/Inactive 列表)

使用方法:
    uv run main.py
    或
    python main.py
"""
from memory_ui import MemSimApp

if __name__ == "__main__":
    app = MemSimApp()
    app.run()