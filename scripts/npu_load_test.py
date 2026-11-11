#!/usr/bin/env python3
"""把一个 safetensors 模型逐个张量拷到 NPU，定位「加载模型时卡住 / vector core timeout」。

用法:
  python3 scripts/npu_load_test.py <模型.safetensors> [--ram] [--dtype bf16|fp16|keep] [--limit N]
    --ram    先把张量完整读进内存再拷（等价于 ComfyUI 的 --disable-mmap），用来对比是不是 mmap 读盘导致
    --dtype  非 int8/uint8 的张量拷过去时转成的类型（ComfyUI 文本编码器在 NPU 上一般是 bf16），默认 bf16
建议加 ASCEND_LAUNCH_BLOCKING=1 运行，出错时能精确停在出问题的那个张量。
"""
import argparse
import os
import sys
import time

import torch
import torch_npu  # noqa: F401
from safetensors import safe_open


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--ram", action="store_true")
    ap.add_argument("--dtype", default="bf16", choices=["bf16", "fp16", "keep"])
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    target = {"bf16": torch.bfloat16, "fp16": torch.float16, "keep": None}[a.dtype]
    dev = torch.device("npu:0")

    print(f"torch {torch.__version__} / torch_npu {torch_npu.__version__} / npu_available={torch.npu.is_available()}")
    print(f"ASCEND_LAUNCH_BLOCKING={os.environ.get('ASCEND_LAUNCH_BLOCKING', '')}  mode={'RAM' if a.ram else 'mmap'}  dtype={a.dtype}")

    # 1) 基础自检：H2D 拷贝 + 类型转换 + matmul
    t0 = time.time()
    x = torch.randn(4096, 4096)
    y = x.to(dev, dtype=torch.bfloat16)
    z = (y @ y).float().sum()
    torch.npu.synchronize()
    print(f"[自检] H2D+cast+matmul OK ({time.time() - t0:.1f}s, sum={z.item():.3e})")

    # 2) 逐个张量拷贝
    total = 0
    slow = []
    t_all = time.time()
    with safe_open(a.path, framework="pt", device="cpu") as f:
        keys = list(f.keys())
        print(f"{len(keys)} 个张量: {a.path}")
        for i, k in enumerate(keys):
            if a.limit and i >= a.limit:
                break
            t = f.get_tensor(k)
            if a.ram:
                t = t.clone()
            dt = None if (target is None or t.dtype in (torch.int8, torch.uint8) or not t.is_floating_point()) else target
            t1 = time.time()
            try:
                g = t.to(device=dev, dtype=dt) if dt is not None else t.to(device=dev)
                torch.npu.synchronize()
            except Exception as e:  # noqa: BLE001
                print(f"\n!! 第 {i} 个张量出错: {k} shape={tuple(t.shape)} dtype={t.dtype} -> {dt}")
                print(f"   {type(e).__name__}: {str(e)[:500]}")
                sys.exit(1)
            el = time.time() - t1
            total += t.numel() * t.element_size()
            if el > 5:
                slow.append((el, k, tuple(t.shape), t.dtype))
                print(f"  慢: {k} {tuple(t.shape)} {t.dtype} 用了 {el:.1f}s")
            del g
            if i % 100 == 0:
                print(f"  [{i}/{len(keys)}] 已拷 {total / 1e9:.2f}GB, {time.time() - t_all:.0f}s", flush=True)
    el = time.time() - t_all
    print(f"完成: {total / 1e9:.2f}GB 用时 {el:.0f}s（{total / 1e6 / max(el, 1e-6):.0f} MB/s），慢张量 {len(slow)} 个")


if __name__ == "__main__":
    main()
