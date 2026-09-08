#!/usr/bin/env python3
import argparse
import json
import os
import posixpath
import stat
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def format_file_size(size):
    value = float(size or 0)
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if value < 1024 or unit == 'TB':
            precision = 0 if unit == 'B' else 2
            return f'{value:.{precision}f} {unit}'
        value /= 1024


def timestamp_from_stat(stat_result):
    return datetime.fromtimestamp(
        stat_result.st_mtime,
        tz=timezone.utc,
    ).isoformat()


def build_resource_tree(storage_root, source='https://resour.nwu.icu'):
    storage_root = Path(storage_root).resolve(strict=True)
    if not storage_root.is_dir():
        raise ValueError(f'存储根路径不是目录：{storage_root}')

    root_stat = storage_root.stat()
    directory_paths = {'/'}
    entries = [{
        'path': '/',
        'name': '/',
        'type': 'directory',
        'size': None,
        'size_display': None,
        'modified_at': timestamp_from_stat(root_stat),
    }]
    stack = [(storage_root, '/')]

    while stack:
        physical_directory, virtual_directory = stack.pop()
        with os.scandir(physical_directory) as iterator:
            children = sorted(iterator, key=lambda item: item.name.casefold())

        child_directories = []
        for child in children:
            if child.name.startswith('.'):
                continue
            virtual_path = posixpath.join(virtual_directory, child.name)
            stat_result = child.stat(follow_symlinks=False)
            if getattr(stat_result, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                continue
            if child.is_dir(follow_symlinks=False):
                directory_paths.add(virtual_path)
                entries.append({
                    'path': virtual_path,
                    'name': child.name,
                    'type': 'directory',
                    'size': None,
                    'size_display': None,
                    'modified_at': timestamp_from_stat(stat_result),
                })
                child_directories.append((Path(child.path), virtual_path))
            elif child.is_file(follow_symlinks=False):
                entries.append({
                    'path': virtual_path,
                    'name': child.name,
                    'type': 'file',
                    'size': stat_result.st_size,
                    'size_display': format_file_size(stat_result.st_size),
                    'modified_at': timestamp_from_stat(stat_result),
                })
            elif child.is_symlink():
                entries.append({
                    'path': virtual_path,
                    'name': child.name,
                    'type': 'symlink',
                    'size': None,
                    'size_display': None,
                    'modified_at': timestamp_from_stat(stat_result),
                    'target': os.readlink(child.path),
                })

        # 反向压栈，保持实际 DFS 输出顺序与按名称升序遍历一致。
        stack.extend(reversed(child_directories))

    file_count = sum(entry['type'] == 'file' for entry in entries)
    total_file_size = sum(
        entry['size'] or 0
        for entry in entries
        if entry['type'] == 'file'
    )
    return {
        'version': 1,
        'updated_at': datetime.now(timezone.utc).isoformat(),
        'source': source.rstrip('/'),
        'storage_root': str(storage_root),
        'summary': {
            'directory_count': len(directory_paths),
            'file_count': file_count,
            'total_file_size': total_file_size,
            'total_file_size_display': format_file_size(total_file_size),
        },
        # 后端投稿目录选择使用的快速索引。
        'paths': sorted(directory_paths),
        # 完整文件树，包含目录、文件和未跟随的符号链接。
        'entries': entries,
    }


def write_json_atomically(payload, output_file):
    output_file = Path(output_file)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    temporary_file = None
    try:
        with tempfile.NamedTemporaryFile(
                mode='w',
                encoding='utf-8',
                dir=output_file.parent,
                prefix=output_file.name + '.',
                suffix='.tmp',
                delete=False,
        ) as file:
            temporary_file = Path(file.name)
            json.dump(payload, file, ensure_ascii=False, indent=2)
            file.write('\n')
        os.replace(temporary_file, output_file)
    finally:
        if temporary_file and temporary_file.exists():
            temporary_file.unlink()


def parse_args():
    parser = argparse.ArgumentParser(
        description='从 AList 本地存储目录 DFS 导出完整文件树 JSON',
        epilog=(
            'cron 示例：0 3 * * * /usr/bin/python3 /opt/export_resource_tree.py '
            '--root /data/resources --output /tmp/resource_directories.json'
        ),
    )
    parser.add_argument('--root', required=True, help='AList Local 存储驱动对应的物理根目录')
    parser.add_argument('--output', required=True, help='输出 JSON 文件路径')
    parser.add_argument('--source', default='https://resour.nwu.icu', help='资源站公开地址')
    return parser.parse_args()


def main():
    args = parse_args()
    payload = build_resource_tree(args.root, source=args.source)
    write_json_atomically(payload, args.output)
    summary = payload['summary']
    print(
        f'导出完成：{summary["directory_count"]} 个目录，'
        f'{summary["file_count"]} 个文件，'
        f'共 {summary["total_file_size_display"]}；输出到 {args.output}'
    )


if __name__ == '__main__':
    main()
