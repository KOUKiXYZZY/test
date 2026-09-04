#!/usr/bin/env python3
# usage: python smart_merge.py left.txt right.txt "キーワード" -o merged.txt
import argparse
import sys

from java_block_diff import PlainSequenceMatcher

def smart_merge(left_lines, right_lines, keyword):
    """差分ブロックごとに、左側にキーワードがあれば左を、なければ右を採用する"""
    sm = PlainSequenceMatcher(None, left_lines, right_lines, autojunk=False)
    merged = []

    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            # 一致ブロックはそのまま採用
            merged.extend(left_lines[i1:i2])
        elif tag == "insert":
            # 右側にしか存在しない行は無条件で採用
            merged.extend(right_lines[j1:j2])
        else:
            # replace / delete: 左ブロックにキーワードがあれば左側を優先
            left_block = left_lines[i1:i2]
            if any(keyword in line for line in left_block):
                merged.extend(left_block)
            else:
                merged.extend(right_lines[j1:j2])
    return merged

def read_lines(path, encoding):
    with open(path, "r", encoding=encoding, newline="") as f:
        return f.readlines()

def main():
    p = argparse.ArgumentParser(description="diff-based smart merge")
    p.add_argument("left")
    p.add_argument("right")
    p.add_argument("keyword")
    p.add_argument("-o", "--output", default=None)
    p.add_argument("--encoding", default="utf-8",
                   help="utf-8 / cp932 など (default: utf-8)")
    args = p.parse_args()

    left_lines = read_lines(args.left, args.encoding)
    right_lines = read_lines(args.right, args.encoding)

    merged = smart_merge(left_lines, right_lines, args.keyword)

    if args.output:
        with open(args.output, "w", encoding=args.encoding, newline="") as f:
            f.writelines(merged)
    else:
        sys.stdout.writelines(merged)

if __name__ == "__main__":
    main()
