"""内置工具：框架层提供的默认工具工厂（当前仅 task 委派工具）。"""
from .task import make_task_tool

__all__ = ["make_task_tool"]
