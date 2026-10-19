#!/usr/bin/env python3
"""兼容入口：委托统一模型部署器。"""
import sys
from deploy import main

if __name__ == '__main__':
    sys.argv[1:1] = ['--service', 'aerovla']
    main()
