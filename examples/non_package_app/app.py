from pathlib import Path

from utils.message import message

print(message())
print(f"cwd={Path.cwd().name}")
