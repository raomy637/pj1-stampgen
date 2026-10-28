import subprocess

OPENSCAD_PATH = r"D:\OpenSCAD\openscad.exe"  # ← 按上面确认后的实际文件名改

try:
    result = subprocess.run(
        [OPENSCAD_PATH, "-v"],
        check=True,
        capture_output=True,
        text=True
    )
    print("调用成功，版本信息：")
    print(result.stdout or result.stderr)
except FileNotFoundError:
    print("找不到 OpenSCAD，可能文件路径不对。")
except PermissionError as e:
    print("权限错误：", e)
except subprocess.CalledProcessError as e:
    print("OpenSCAD 返回错误：", e)
