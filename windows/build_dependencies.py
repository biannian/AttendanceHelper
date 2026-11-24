# Copyright (c) iGroup.
# All rights reserved.
"""构建原生依赖定位。@author Kai @date 2026/10/26 11:19 @description 从实际 Python SSL 模块目录定位 DLL，禁止猜测盘符或依赖 PATH。"""

import _ssl
import json
import sys
from pathlib import Path


def main():
    """输出经文件存在校验的 DLL 绝对路径。@return 标准输出 JSON @author Kai @date 2026/10/26 11:19"""
    # 优先实际 SSL 扩展目录，兼容 uv Python、常规安装和不同虚拟环境布局。
    folders = [Path(_ssl.__file__).resolve().parent, Path(sys.base_prefix) / "DLLs", Path(sys.base_prefix)]
    result = {}
    for key, filename in [("crypto", "libcrypto-3-x64.dll"), ("ssl", "libssl-3-x64.dll")]:
        path = next((folder / filename for folder in folders if (folder / filename).is_file()), None)
        if path is None:
            raise FileNotFoundError(f"Python 配套依赖不存在：{filename}")
        result[key] = str(path.resolve())
    print(json.dumps(result))


if __name__ == "__main__":
    main()
