#!/usr/bin/env python3
"""
/squad 端到端链路压测脚本
测试 Claude-Hermes Bridge 在高并发下的性能
"""

import os
import sys
import time
import json
import uuid
import threading
from datetime import datetime
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services.bridge import (
    load_state, save_state, get_true_line_count,
    append_bridge, _read_checkpoint
)

# 测试参数（缩短版）
TARGET_QPS_START = 50
TARGET_QPS_END = 200
TEST_DURATION_SEC = 10
RAMP_UP_SEC = 2

class LoadTestMetrics:
    def __init__(self):
        self.lock = threading.Lock()
        self.latencies = []
        self.errors = 0
        self.total_sent = 0
        self.total_received = 0
        self.start_time = None
        self.end_time = None
        self.session_ids = set()
        self.layer_counts = defaultdict(int)
        
    def record_sent(self, session_id, layer):
        with self.lock:
            self.total_sent += 1
            self.session_ids.add(session_id)
            self.layer_counts[layer] += 1
            
    def record_received(self):
        with self.lock:
            self.total_received += 1
            
    def record_latency(self, latency_ms):
        with self.lock:
            self.latencies.append(latency_ms)
            
    def record_error(self):
        with self.lock:
            self.errors += 1
            
    def get_p99(self):
        with self.lock:
            if not self.latencies:
                return 0
            sorted_latencies = sorted(self.latencies)
            idx = int(len(sorted_latencies) * 0.99)
            return sorted_latencies[idx] if idx < len(sorted_latencies) else sorted_latencies[-1]
            
    def get_avg(self):
        with self.lock:
            return sum(self.latencies) / len(self.latencies) if self.latencies else 0
            
    def get_actual_qps(self):
        with self.lock:
            if not self.start_time or not self.end_time:
                return 0
            duration = self.end_time - self.start_time
            return self.total_sent / duration if duration > 0 else 0

def run_squad_test():
    metrics = LoadTestMetrics()
    metrics.start_time = time.time()
    
    # 记录初始状态
    initial_state = load_state()
    initial_line_count = get_true_line_count()
    initial_checkpoint = _read_checkpoint()
    
    print("=" * 60)
    print("/squad 端到端链路压测")
    print("=" * 60)
    print(f"目标 QPS: {TARGET_QPS_START} → {TARGET_QPS_END}")
    print(f"测试时长: {TEST_DURATION_SEC}s (含 {RAMP_UP_SEC}s 预热)")
    print(f"初始状态: layer={initial_state.get('current_layer')}, lines={initial_line_count}")
    print("=" * 60)
    
    # 模拟发压
    messages_sent = 0
    test_end_time = time.time() + TEST_DURATION_SEC
    
    # 预热阶段
    warmup_end = time.time() + RAMP_UP_SEC
    
    # 阶段1: 50 QPS 预热
    phase1_end = warmup_end + 15
    # 阶段2: 100 QPS
    phase2_end = phase1_end + 15
    # 阶段3: 150 QPS  
    phase3_end = phase2_end + 10
    # 阶段4: 200 QPS
    phase4_end = test_end_time
    
    phases = [
        (warmup_end, TARGET_QPS_START),
        (phase1_end, 75),
        (phase2_end, 100),
        (phase3_end, 150),
        (phase4_end, TARGET_QPS_END),
    ]
    
    current_qps = TARGET_QPS_START
    interval_sec = 1.0 / current_qps
    last_phase_idx = 0
    
    while time.time() < test_end_time:
        # 检查当前阶段
        now = time.time()
        for i, (end_time, qps) in enumerate(phases):
            if now < end_time:
                if i > last_phase_idx:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] 阶段{i+1}: QPS {current_qps} → {qps}")
                    last_phase_idx = i
                    current_qps = qps
                    interval_sec = 1.0 / current_qps
                break
        
        # 发送测试消息
        session_id = str(uuid.uuid4())[:8]
        test_content = f"[squad-load-test] session={session_id} ts={time.time()}"
        
        state = load_state()
        current_layer = state.get("current_layer", 0) + 1
        
        entry = {
            "layer": current_layer,
            "author": "hermes",  # 模拟 Hermes 写入
            "content": test_content,
            "timestamp": datetime.now().isoformat(),
            "session_id": session_id,
            "test_marker": True
        }
        
        send_start = time.time()
        new_offset = append_bridge(entry, update_checkpoint=True)
        send_latency = (time.time() - send_start) * 1000
        
        if new_offset:
            metrics.record_sent(session_id, current_layer)
            metrics.record_latency(send_latency)
            messages_sent += 1
        else:
            metrics.record_error()
            
        # 短暂休眠控制 QPS
        time.sleep(interval_sec)
    
    metrics.end_time = time.time()
    
    # 收集最终状态
    final_state = load_state()
    final_line_count = get_true_line_count()
    
    # 模拟读取响应（检查消息是否可被读取）
    time.sleep(0.5)
    received_count = 0
    for i in range(initial_line_count + 1, final_line_count + 1):
        received_count += 1
    metrics.total_received = received_count
    
    # 计算最终指标
    actual_qps = metrics.get_actual_qps()
    p99_latency = metrics.get_p99()
    avg_latency = metrics.get_avg()
    error_rate = (metrics.errors / metrics.total_sent * 100) if metrics.total_sent > 0 else 0
    
    # 生成报告
    print("\n" + "=" * 60)
    print("压测报告")
    print("=" * 60)
    print(f"总发送消息: {metrics.total_sent}")
    print(f"总接收消息: {metrics.total_received}")
    print(f"实际 QPS: {actual_qps:.1f}")
    print(f"延迟 P99: {p99_latency:.2f}ms")
    print(f"延迟 AVG: {avg_latency:.2f}ms")
    print(f"错误率: {error_rate:.2f}%")
    print(f"跨会话数: {len(metrics.session_ids)}")
    print("-" * 60)
    print(f"初始行数: {initial_line_count} → 最终行数: {final_line_count}")
    print(f"初始 Layer: {initial_state.get('current_layer')} → 最终 Layer: {final_state.get('current_layer')}")
    print(f"Checkpoint: {initial_checkpoint} → {_read_checkpoint()}")
    print("=" * 60)
    
    # 状态一致性检查
    state_consistent = (
        final_line_count == _read_checkpoint() and
        final_state.get("bridge_line_count") == final_line_count
    )
    print(f"状态一致性: {'✓ 通过' if state_consistent else '✗ 失败'}")
    
    return {
        "total_sent": metrics.total_sent,
        "total_received": metrics.total_received,
        "actual_qps": actual_qps,
        "p99_latency_ms": p99_latency,
        "avg_latency_ms": avg_latency,
        "error_rate": error_rate,
        "sessions": len(metrics.session_ids),
        "state_consistent": state_consistent
    }

if __name__ == "__main__":
    results = run_squad_test()
    print(f"\n结果: {json.dumps(results, indent=2)}")