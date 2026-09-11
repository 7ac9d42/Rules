#!/usr/bin/env python3
"""验证当前配置的AI默认、主动覆盖和重启保留；复用完整生命周期回归。"""
from pathlib import Path
import runpy

if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).with_name("test-runtime-lifecycle.py")), run_name="__main__")
