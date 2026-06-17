"""Quark cloud storage organizer — classify, deduplicate, rename, and clean up."""

import re
import time
import json
import sys
from dataclasses import dataclass, field
from typing import Optional

from .api import QuarkClient
from .cookie import CookieManager


# ── Grade detection ──────────────────────────────────────────────────

GRADE_PATTERNS = [
    (re.compile(r"一年级|1年级|一下|一\(下\)|一（下）|1下|1\(下\)|(?:^|[^0-9])1下"), "一年级"),
    (re.compile(r"二年级|2年级|二下|二\(下\)|二（下）|2下|2\(下\)"), "二年级"),
    (re.compile(r"三年级|3年级|三下|三\(下\)|三（下）|3下|3\(下\)|RJ3[下]?"), "三年级"),
    (re.compile(r"四年级|4年级|四下|四\(下\)|四（下）|4下|4\(下\)|26新四|新四"), "四年级"),
    (re.compile(r"五年级|5年级|五下|五\(下\)|五（下）|5下|5\(下\)"), "五年级"),
    (re.compile(r"六年级|6年级|六下|六\(下\)|六（下）|6下|6\(下\)|6下U"), "六年级"),
    (re.compile(r"小升初|小初衔接|预备新初一|初一预备"), "小升初"),
    (re.compile(r"初中|中考|7年级|8年级|9年级|七下|八下|九下|7下|8下|9下"), "初中"),
]

SUBJECT_PATTERNS = [
    # English must be checked FIRST — keywords like PEP, 英语 are unambiguous
    (re.compile(r"英语|PEP|英文|单词|口语|小学英语|RJ[3-6]下*\s*英语"), "英语"),
    (re.compile(r"数学|口算|计算.*题|应用题|几何|数学报|扬帆金考|黄冈名卷.*数学|实验班.*数学"), "数学"),
    (re.compile(r"语文|阅读|作文|默写|字词|句子|拼音|写字|课文|古诗词|日积月累|一本.*语文|一本.*阅读"), "语文"),
    (re.compile(r"科学|物理|化学|生物|道法|历史|地理"), "综合"),
    # Audio files are usually English listening practice
    (re.compile(r"\.mp3$|\.MP3$|音频"), "英语"),
]


def detect_grade(name: str) -> str:
    for pattern, grade in GRADE_PATTERNS:
        if pattern.search(name):
            return grade
    return "未分类"


def detect_subject(name: str) -> str:
    for pattern, subject in SUBJECT_PATTERNS:
        if pattern.search(name):
            return subject
    return "其他"


# ── Duplicate detection ──────────────────────────────────────────────

def normalize_name(name: str) -> str:
    """Strip (1), (2), _1, _2, 副本 suffixes and page-extract for dedup comparison."""
    name = re.sub(r"[\s_-]*-\s*页面提取(?=\.\w+$|$)", "", name)
    name = re.sub(r"[\s_-]*(\(\d+\)|（\d+）|副本|-\s*副本|_\d+)(?=\.\w+$|$)", "", name)
    return name


def find_duplicates(files: list[dict]) -> list[list[dict]]:
    """Group files by (normalized_name, size). Returns groups with >1 member."""
    groups: dict[tuple[str, int], list[dict]] = {}
    for f in files:
        key = (normalize_name(f["name"]), f.get("size", 0))
        groups.setdefault(key, []).append(f)
    return [g for g in groups.values() if len(g) > 1]


# ── Flat scan ────────────────────────────────────────────────────────

def list_entries(client: QuarkClient, fid: str, path: str) -> list[dict]:
    """List all files and folders in a single directory."""
    entries = []
    page = 1
    while True:
        resp = client.list_folder(fid, page=page, size=200)
        batch = resp.get("data", {}).get("list", [])
        entries.extend(batch)
        total = resp.get("data", {}).get("total", 0)
        if total == 0 or page * 200 >= total:
            break
        page += 1

    result = []
    for e in entries:
        if e.get("dir"):
            result.append({
                "type": "folder",
                "name": e.get("file_name", "unknown"),
                "fid": e.get("fid", ""),
                "parent_fid": fid,
                "parent_path": path,
            })
        else:
            result.append({
                "type": "file",
                "name": e.get("file_name", "unknown"),
                "fid": e.get("fid", ""),
                "size": e.get("size", 0),
                "parent_fid": fid,
                "parent_path": path,
            })
    return result


# ── Organization plan ────────────────────────────────────────────────

@dataclass
class Operation:
    type: str  # create_folder, move, delete, rename
    detail: str
    data: dict


SYSTEM_FOLDERS = {
    "夸克快传", "夸克上传文件", "夸克云解压", "来自：分享", "来自：云收藏",
    "PDF页面提取", "我的备份", "文档工具", "我的扫描件",
}


class Organizer:
    def __init__(self, client: QuarkClient, dry_run: bool = True):
        self.client = client
        self.dry_run = dry_run
        self.ops: list[Operation] = []
        self.stats = {"create": 0, "move": 0, "delete": 0, "rename": 0, "errors": 0}

    def scan_and_plan(self):
        """Scan target folders and build organization plan."""
        print("正在扫描根目录...")
        root_entries = list_entries(self.client, "0", "/")
        print(f"  根目录: {len(root_entries)} 项")

        # Find the "来自：分享" folder fid
        share_fid = None
        for e in root_entries:
            if e["type"] == "folder" and e["name"] == "来自：分享":
                share_fid = e["fid"]
                break

        share_entries = []
        if share_fid:
            print("正在扫描 来自：分享...")
            share_entries = list_entries(self.client, share_fid, "/来自：分享")
            print(f"  来自：分享: {len(share_entries)} 项")

        # Combine all files from both locations
        all_files = [e for e in root_entries if e["type"] == "file"]
        all_files += [e for e in share_entries if e["type"] == "file"]

        # Also check root folders for junk
        root_folders = [e for e in root_entries if e["type"] == "folder"]

        # Track fids to delete (don't move them later)
        deleted_fids: set[str] = set()

        # 1. Detect duplicates
        dups = find_duplicates(all_files)
        for group in dups:
            group.sort(key=lambda f: len(f["name"]))
            keep = group[0]
            for dup in group[1:]:
                deleted_fids.add(dup["fid"])
                self.ops.append(Operation(
                    type="delete",
                    detail=f"删除重复: {dup['parent_path']}/{dup['name']} (保留 {keep['name']})",
                    data={"parent_fid": dup["parent_fid"], "filelist": [dup["fid"]]},
                ))

        # 2. Classify and move files (skip those marked for deletion)
        for f in all_files:
            if f["fid"] in deleted_fids:
                continue
            name = f["name"]
            parent = f.get("parent_path", "/")
            grade = detect_grade(name)
            subject = detect_subject(name)

            if grade == "未分类":
                continue

            # Determine target path
            target = f"/{grade}"
            if subject != "其他":
                target = f"/{grade}/{subject}"

            self.ops.append(Operation(
                type="move",
                detail=f"移动: {parent}/{name} -> {target}/",
                data={
                    "parent_fid": f["parent_fid"],
                    "filelist": [f["fid"]],
                    "dest_path": target,
                },
            ))

        # 3. Cleanup junk folders
        junk_patterns = [re.compile(r"新建文件夹")]
        for f in root_folders:
            for pat in junk_patterns:
                if pat.search(f["name"]):
                    # Check if empty
                    sub = list_entries(self.client, f["fid"], f"/{f['name']}")
                    if len(sub) == 0:
                        self.ops.append(Operation(
                            type="delete",
                            detail=f"删除空文件夹: /{f['name']}",
                            data={"parent_fid": f["parent_fid"], "filelist": [f["fid"]]},
                        ))

        # 4. Rename: remove (1) suffix and -页面提取 from non-duplicate files
        for f in all_files:
            if f["fid"] in deleted_fids:
                continue
            name = f["name"]
            new_name = normalize_name(name)
            # Also remove -页面提取
            new_name = re.sub(r"-\s*页面提取", "", new_name)
            if new_name != name and f["fid"] not in {
                dup["fid"] for group in dups for dup in group[1:]
            }:
                self.ops.append(Operation(
                    type="rename",
                    detail=f"重命名: {name} -> {new_name}",
                    data={"fid": f["fid"], "new_name": new_name},
                ))

    def print_plan(self):
        for i, op in enumerate(self.ops, 1):
            icon = {"create": "📁", "move": "📦", "delete": "🗑️", "rename": "✏️"}.get(op.type, "?")
            print(f"  {i}. {icon} {op.detail}")

    def execute(self):
        created_folders: dict[str, str] = {}

        for i, op in enumerate(self.ops, 1):
            try:
                if op.type == "create":
                    if self.dry_run:
                        print(f"  [DRY RUN] 创建: {op.detail}")
                        continue
                    fid = self.client.create_folder(op.data["parent_fid"], op.data["name"])
                    created_folders[op.data.get("path", "")] = fid
                    print(f"  ✅ {op.detail}")

                elif op.type == "move":
                    if self.dry_run:
                        print(f"  [DRY RUN] {op.detail}")
                        continue
                    dest_path = op.data.get("dest_path", "")
                    dest_fid = created_folders.get(dest_path)
                    if dest_fid is None:
                        dest_fid = self._ensure_path(dest_path, created_folders)
                    self.client.move_files(op.data["parent_fid"], op.data["filelist"], dest_fid)
                    print(f"  ✅ {op.detail}")

                elif op.type == "delete":
                    if self.dry_run:
                        print(f"  [DRY RUN] {op.detail}")
                        continue
                    self.client.delete_files(op.data["parent_fid"], op.data["filelist"])
                    print(f"  ✅ {op.detail}")

                elif op.type == "rename":
                    if self.dry_run:
                        print(f"  [DRY RUN] {op.detail}")
                        continue
                    self.client.rename_file(op.data["fid"], op.data["new_name"])
                    print(f"  ✅ {op.detail}")

                self.stats[op.type] += 1
            except Exception as e:
                print(f"  ❌ 失败 [{op.type}]: {op.detail} — {e}")
                self.stats["errors"] += 1

    def _ensure_path(self, path: str, cache: dict[str, str]) -> str:
        if path in cache:
            return cache[path]

        parts = [p for p in path.strip("/").split("/") if p]
        current_fid = "0"
        current_path = ""

        for part in parts:
            current_path = f"{current_path}/{part}"
            if current_path in cache:
                current_fid = cache[current_path]
                continue
            found = self.client._find_child_folder(current_fid, part)
            if found:
                current_fid = found
                cache[current_path] = found
            else:
                current_fid = self.client.create_folder(current_fid, part)
                cache[current_path] = current_fid
                print(f"  📁 创建文件夹: {current_path}")

        return current_fid


# ── CLI ──────────────────────────────────────────────────────────────

def run_organize(cookies_path: str = "config/cookies.json", dry_run: bool = True):
    cm = CookieManager(cookies_path)
    client = QuarkClient(cm)
    try:
        print("正在分析夸克网盘...")
        organizer = Organizer(client, dry_run=dry_run)
        organizer.scan_and_plan()
        print()
        organizer.print_plan()

        print(f"\n共 {len(organizer.ops)} 个操作")

        if dry_run:
            print("\n🔍 这是预览模式，没有实际修改任何文件。")
            print("   加上 --execute 参数执行实际操作。")
        else:
            print("\n⚡ 执行整理...")
            organizer.execute()
            total_ok = sum(v for k, v in organizer.stats.items() if k != "errors")
            print(f"\n完成! 成功 {total_ok} 个操作")
            if organizer.stats["errors"]:
                print(f"失败 {organizer.stats['errors']} 个操作")
    finally:
        client.close()


if __name__ == "__main__":
    dry_run = "--execute" not in sys.argv
    cookies = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else "config/cookies.json"
    run_organize(cookies, dry_run=dry_run)
