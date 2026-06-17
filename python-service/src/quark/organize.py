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
    (re.compile(r"一年级|1年级|一下|一\(下\)|一（下）|1下|1\(下\)"), "一年级"),
    (re.compile(r"二年级|2年级|二下|二\(下\)|二（下）|2下|2\(下\)"), "二年级"),
    (re.compile(r"三年级|3年级|三下|三\(下\)|三（下）|3下|3\(下\)|RJ3"), "三年级"),
    (re.compile(r"四年级|4年级|四下|四\(下\)|四（下）|4下|4\(下\)|26新四"), "四年级"),
    (re.compile(r"五年级|5年级|五下|五\(下\)|五（下）|5下|5\(下\)"), "五年级"),
    (re.compile(r"六年级|6年级|六下|六\(下\)|六（下）|6下|6\(下\)|6下U"), "六年级"),
    (re.compile(r"小升初|小初衔接|预备新初一|初一预备"), "小升初"),
    (re.compile(r"初中|中考|7年级|8年级|9年级|七下|八下|九下|7下|8下|9下"), "初中"),
]

SUBJECT_PATTERNS = [
    (re.compile(r"数学|口算|计算|应用题|几何|苏教|人教|北师大|北师|黄冈.*数学|实验班.*数学"), "数学"),
    (re.compile(r"语文|阅读|作文|默写|字词|句子|拼音|写字|课文|古诗词|一本.*语文|一本.*阅读"), "语文"),
    (re.compile(r"英语|PEP|RJ[3-6]|RJ\s*[3-6]|英文|单词|听力|口语|小学英语"), "英语"),
    (re.compile(r"科学|物理|化学|生物|道法|历史|地理"), "综合"),
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
    """Strip (1), (2), 副本, -副本, _1, _2 suffixes for dedup comparison."""
    return re.sub(
        r"[\s_-]*(\(\d+\)|（\d+）|副本|-\s*副本|_\d+)(?=\.\w+$|$)",
        "", name,
    )


def find_duplicates(files: list[dict]) -> list[list[dict]]:
    """Group files by (normalized_name, size). Returns groups with >1 member."""
    groups: dict[tuple[str, int], list[dict]] = {}
    for f in files:
        key = (normalize_name(f["name"]), f.get("size", 0))
        groups.setdefault(key, []).append(f)
    return [g for g in groups.values() if len(g) > 1]


# ── Recursive scan ───────────────────────────────────────────────────

@dataclass
class ScanResult:
    path: str
    fid: str
    parent_fid: str
    folders: list["ScanResult"] = field(default_factory=list)
    files: list[dict] = field(default_factory=list)


def scan_tree(client: QuarkClient, fid: str = "0", path: str = "/",
              parent_fid: str = "0", depth: int = 0, max_depth: int = 5) -> ScanResult:
    """Recursively scan the Quark drive."""
    result = ScanResult(path=path, fid=fid, parent_fid=parent_fid)
    page = 1
    all_entries = []
    while True:
        resp = client.list_folder(fid, page=page, size=200)
        entries = resp.get("data", {}).get("list", [])
        all_entries.extend(entries)
        total = resp.get("data", {}).get("total", 0)
        if total == 0 or page * 200 >= total:
            break
        page += 1

    for e in all_entries:
        if e.get("dir"):
            sub_path = f"{path}/{e['file_name']}" if path != "/" else f"/{e['file_name']}"
            if depth < max_depth:
                sub = scan_tree(client, e["fid"], sub_path, fid, depth + 1, max_depth)
                result.folders.append(sub)
            else:
                result.folders.append(ScanResult(
                    path=sub_path, fid=e["fid"], parent_fid=fid,
                ))
        else:
            result.files.append({
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
    detail: str  # human-readable description
    data: dict  # API params


class Organizer:
    def __init__(self, client: QuarkClient, dry_run: bool = True):
        self.client = client
        self.dry_run = dry_run
        self.ops: list[Operation] = []
        self.stats = {"create": 0, "move": 0, "delete": 0, "rename": 0, "errors": 0}

    def plan(self, scan: ScanResult):
        """Generate organization plan."""
        # Flatten all files from everywhere
        all_files: list[dict] = []
        folder_map: dict[str, str] = {}  # fid -> path

        def walk(node: ScanResult):
            folder_map[node.fid] = node.path
            for f in node.files:
                all_files.append(f)
            for sub in node.folders:
                walk(sub)

        walk(scan)

        # Find duplicates
        dups = find_duplicates(all_files)
        for group in dups:
            # Keep the one with shortest name (no suffix), delete others
            group.sort(key=lambda f: len(f["name"]))
            keep = group[0]
            for dup in group[1:]:
                self.ops.append(Operation(
                    type="delete",
                    detail=f"删除重复: {dup['parent_path']}/{dup['name']} (保留 {keep['name']})",
                    data={"parent_fid": dup["parent_fid"], "filelist": [dup["fid"]]},
                ))

        # Classify and move root-level files
        for f in all_files:
            name = f["name"]
            parent = f.get("parent_path", "/")

            # Only move files at root level or in 来自：分享
            if parent not in ("/", "/来自：分享"):
                continue

            grade = detect_grade(name)
            subject = detect_subject(name)

            if grade == "未分类":
                continue

            target = f"/{grade}/{subject}" if subject != "其他" else f"/{grade}"
            self.ops.append(Operation(
                type="move",
                detail=f"移动: {parent}/{name} -> {target}/",
                data={
                    "parent_fid": f["parent_fid"],
                    "filelist": [f["fid"]],
                    "dest_path": target,
                },
            ))

        # Cleanup: find empty junk folders
        junk_names = {"新建文件夹", "新建文件夹-"}
        for node in scan.folders:
            if any(node.path.endswith(j) or j in node.path.split("/")[-1]
                   for j in junk_names):
                if not node.files and not node.folders:
                    self.ops.append(Operation(
                        type="delete",
                        detail=f"删除空文件夹: {node.path}",
                        data={"parent_fid": node.parent_fid, "filelist": [node.fid]},
                    ))

    def print_plan(self):
        for i, op in enumerate(self.ops, 1):
            icon = {"create": "📁", "move": "📦", "delete": "🗑️", "rename": "✏️"}.get(op.type, "?")
            print(f"  {i}. {icon} {op.detail}")

    def execute(self):
        """Execute the plan, creating target folders as needed."""
        created_folders: dict[str, str] = {}  # path -> fid

        for i, op in enumerate(self.ops, 1):
            try:
                if op.type == "create":
                    if self.dry_run:
                        print(f"  [DRY RUN] 创建: {op.detail}")
                        continue
                    fid = self.client.create_folder(
                        op.data["parent_fid"], op.data["name"],
                    )
                    created_folders[op.data.get("path", "")] = fid

                elif op.type == "move":
                    dest_path = op.data.get("dest_path", "")
                    if self.dry_run:
                        print(f"  [DRY RUN] {op.detail}")
                        continue
                    # Resolve or create target folder
                    dest_fid = created_folders.get(dest_path)
                    if dest_fid is None:
                        dest_fid = self._ensure_path(dest_path, created_folders)
                    self.client.move_files(
                        op.data["parent_fid"], op.data["filelist"], dest_fid,
                    )
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
        """Ensure folder path exists, creating intermediate folders as needed.
        Returns the leaf folder's fid."""
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
            # Try to find existing folder
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
        print("正在扫描夸克网盘...")
        start = time.time()
        tree = scan_tree(client)
        elapsed = time.time() - start

        # Count
        def count_nodes(n: ScanResult):
            nf = len(n.files)
            nd = len(n.folders)
            for s in n.folders:
                sf, sd = count_nodes(s)
                nf += sf
                nd += sd
            return nf, nd

        total_files, total_dirs = count_nodes(tree)
        print(f"扫描完成 ({elapsed:.1f}s): {total_dirs} 个文件夹, {total_files} 个文件\n")

        organizer = Organizer(client, dry_run=dry_run)
        organizer.plan(tree)
        organizer.print_plan()

        print(f"\n共 {len(organizer.ops)} 个操作")
        print(f"  移动: {organizer.stats['move']} (计划)")
        print(f"  删除: {organizer.stats['delete']} (计划)")
        print(f"  重命名: {organizer.stats['rename']} (计划)")

        if dry_run:
            print("\n🔍 这是预览模式，没有实际修改任何文件。")
            print("   加上 --execute 参数执行实际操作。")
        else:
            print("\n⚡ 执行整理...")
            organizer.execute()
            print(f"\n完成! 成功 {sum(organizer.stats.values()) - organizer.stats['errors']} 个操作")
            if organizer.stats["errors"]:
                print(f"失败 {organizer.stats['errors']} 个操作")
    finally:
        client.close()


if __name__ == "__main__":
    dry_run = "--execute" not in sys.argv
    cookies = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else "config/cookies.json"
    run_organize(cookies, dry_run=dry_run)
