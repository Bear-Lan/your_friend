import argparse
import threading
import webbrowser
from pathlib import Path

import uvicorn

from .app import create_app
from .backup import restore_to_new_directory


def main():
    parser = argparse.ArgumentParser(description="your friend 本机验证版")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open", action="store_true", help="启动后打开本机页面")
    parser.add_argument("--restore-backup", type=Path, help="从一致性备份恢复到一个新目录")
    parser.add_argument("--restore-to", type=Path, help="恢复目标目录，不覆盖已有数据库")
    args = parser.parse_args()
    if args.restore_backup or args.restore_to:
        if not args.restore_backup or not args.restore_to:
            parser.error("恢复需要同时指定 --restore-backup 和 --restore-to")
        try:
            target = restore_to_new_directory(args.restore_backup, args.restore_to)
        except (ValueError, OSError) as error:
            parser.error(str(error))
        print(f"已恢复到：{target}")
        print("这是历史快照，可能包含后来已删除的内容；验证并清理后再切换 YF_DATA_DIR。")
        return
    if args.open:
        timer = threading.Timer(1.5, webbrowser.open, args=(f"http://127.0.0.1:{args.port}",))
        timer.daemon = True
        timer.start()
    uvicorn.run(create_app(), host="127.0.0.1", port=args.port, access_log=False)


if __name__ == "__main__":
    main()
