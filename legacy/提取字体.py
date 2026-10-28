import os
import shutil


def flatten_directory(target_path):
    # 确保路径存在
    if not os.path.exists(target_path):
        print(f"错误：找不到路径 {target_path}")
        return

    print(f"正在处理目录: {target_path}")

    move_count = 0

    # os.walk 采用自底向上模式，方便后续删除空文件夹
    for root, dirs, files in os.walk(target_path, topdown=False):
        # 如果当前是根目录，跳过处理（我们只处理子目录里的文件）
        if root == os.path.abspath(target_path):
            continue

        for name in files:
            source_file = os.path.join(root, name)
            destination_file = os.path.join(target_path, name)

            # 处理文件名冲突：如果根目录已存在同名文件，自动重命名
            base, extension = os.path.splitext(name)
            counter = 1
            while os.path.exists(destination_file):
                destination_file = os.path.join(target_path, f"{base}_{counter}{extension}")
                counter += 1

            try:
                # 使用 move（剪切），同磁盘下速度最快
                shutil.move(source_file, destination_file)
                print(f"提取成功: {os.path.basename(destination_file)}")
                move_count += 1
            except Exception as e:
                print(f"移动失败 {name}: {e}")

        # 文件移动完后，尝试删除已经变空的子文件夹
        try:
            if not os.listdir(root):
                os.rmdir(root)
        except Exception as e:
            pass

    print(f"\n--- 处理完成！ ---")
    print(f"所有子文件夹中的文件已全部提取到：{target_path}")
    print(f"共提取了 {move_count} 个文件。")


if __name__ == "__main__":
    # 你的指定路径
    target_dir = r"E:\BaiduNetdiskDownload\英文字体手写带版权\3英文1415款（备选）\3英文\英-手写和花体"

    # 直接运行
    flatten_directory(target_dir)
    input("\n按回车键退出...")