#!/usr/bin/env python3
"""Print reproducibility commands only. Never execute indexed commands."""
import argparse,json
from pathlib import Path
LAB=Path(__file__).resolve().parents[1]
ENTRIES=json.loads(r'''[
  {
    "id": "patch",
    "title": "pure-guard补丁适用性",
    "mode": "只读证据复核",
    "command": "git -C sources/wine-pin-adea/pristine/wine-adea6cbac9d00bb22910145354d00c463fcf3afc apply --check /Users/mewcapoo/Projects/proton-macos-lab/sources/patch-release/wine-vulkan-reentrancy-guard-adea6cbac.patch",
    "expected": "exit 0；--check不应用补丁、不构建；不是重新验证所有运行时性质",
    "artifacts": [
      {
        "path": "sources/patch-release/wine-vulkan-reentrancy-guard-adea6cbac.patch",
        "sha256": "a22655b6f7b77edabbf0796fe6ad9d613a01cb2282dd27b1d09c29cadc7443a2"
      },
      {
        "path": "sources/patch-release/evidence-summary.json",
        "sha256": "3927f2d153f46fa551ba955a3c70c3e0c0293474a3aecfa231928517ceb680fd"
      },
      {
        "path": "sources/patch-release/apply-check.log",
        "sha256": "b8f91590b5bdaf04ee701f6c0cfe8ec2ff57c58501afa876a2b8f8a4d387a495"
      }
    ]
  },
  {
    "id": "backend",
    "title": "backend既有90项回归",
    "mode": "测试运行（自管临时文件）",
    "command": "PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests/backend",
    "expected": "exit 0，Ran 90 tests，OK；复跑计数可能随后续代码版本变动，应先核SHA",
    "artifacts": [
      {
        "path": "scripts/backend/steam_plan.py",
        "sha256": "104fcda4f31f5e92e871c7d77fda28f630eda58c232bf5d911a4176ce8d0d0aa"
      },
      {
        "path": "logs/compat-package/backend-tests.log",
        "sha256": "241a29e43017b247fbfba972d68866d35a012b969dfe37bec92c71eb850cfb15"
      }
    ]
  },
  {
    "id": "arm64-offscreen",
    "title": "ARM64离屏raw+收据复核（非重新运行guest）",
    "mode": "只读证据复核",
    "expected": "exit 0，8点PASS，framebuffer SHA 2f69987b；normal exit0/skip_draw exit21从现存receipt读取",
    "command": "PYTHONDONTWRITEBYTECODE=1 python3 -I -c 'import sys,hashlib,json;from pathlib import Path;sys.path.insert(0,str(Path.cwd()));from scripts.runtime.vk_offscreen.verify_pixels import verify_framebuffer;p=Path(\"logs/vk-offscreen/framebuffer.raw\");b=p.read_bytes();ok,details=verify_framebuffer(b);print(json.dumps(details,indent=2));assert ok;assert hashlib.sha256(b).hexdigest()==\"2f69987b28f18023bd1dec8c7b23b925fbd20cf62df652fff100c57f20842050\";print(\"PRESERVED_EVIDENCE_ONLY; no guest rerun\")'",
    "artifacts": [
      {
        "path": "sources/vk-offscreen-probe/vk_offscreen_arm64.exe",
        "sha256": "112377ef135b5bb3d240646b665b1747bc21078ec8ee2272208bec2c1ae11e22"
      },
      {
        "path": "logs/vk-offscreen/framebuffer.raw",
        "sha256": "2f69987b28f18023bd1dec8c7b23b925fbd20cf62df652fff100c57f20842050"
      },
      {
        "path": "logs/vk-offscreen/receipt.json",
        "sha256": "f9f94c7b000dca0f831520dc6f75631ad95f3615a297036b20909bfeb7b3cac3"
      },
      {
        "path": "scripts/runtime/vk_offscreen_x64/run_probe.py",
        "sha256": "0302f2443ead54f7474ca6fd3df97379651d9bf5b0a65cdd792a1d8c07ff74ce"
      }
    ],
    "runtime_secondary_command": "PYTHONDONTWRITEBYTECODE=1 python3 -I -c 'import sys,time,importlib.util;from pathlib import Path;sys.path.insert(0,str(Path.cwd()));p=Path(\"scripts/runtime/vk_offscreen_x64/run_probe.py\");spec=importlib.util.spec_from_file_location(\"isolated_replay\",p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);m.OUTPUT_DIR=Path(\"logs/status-check/repro-arm64-\"+str(time.time_ns())).resolve();m.OUTPUT_DIR.mkdir(parents=True,exist_ok=False);m.PROBE_EXE=Path(\"sources/vk-offscreen-probe/vk_offscreen_arm64.exe\").resolve();print(\"REPLAY_PE\",m.PROBE_EXE,\"OUTPUT\",m.OUTPUT_DIR);m.main()'",
    "runtime_secondary_note": "次选实跑：复用无killall的既有x64 runner，显式重定向OUTPUT_DIR与实际PE；ARM64时沿用的内部x64工具/文件名只是标签，架构以实际PE/file/SHA为准。此命令本卡未执行，不新增验证结果；依赖lab sysroot/elfuse/prefix/图形配置，预期运行成功后另核新receipt/raw/rollback。",
    "evidence_binding": "证据需按 run-id 绑定，顶层文件不可单独引用。当前normal root stdout+stderr绑定logs/vk-offscreen/runs/logs/run-l0u2l4b_；vwmj5xtt stdout同hash但stderr不同，不得混算。receipt/framebuffer另核完整SHA。"
  },
  {
    "id": "x64-offscreen",
    "title": "x64离屏raw+收据复核（非重新运行guest）",
    "mode": "只读证据复核",
    "expected": "exit 0，8点PASS，framebuffer SHA 2f69987b；PE aba1c08c",
    "command": "PYTHONDONTWRITEBYTECODE=1 python3 -I -c 'import sys,hashlib,json;from pathlib import Path;sys.path.insert(0,str(Path.cwd()));from scripts.runtime.vk_offscreen.verify_pixels import verify_framebuffer;p=Path(\"logs/vk-offscreen-x64/normal_framebuffer.raw\");b=p.read_bytes();ok,details=verify_framebuffer(b);print(json.dumps(details,indent=2));assert ok;assert hashlib.sha256(b).hexdigest()==\"2f69987b28f18023bd1dec8c7b23b925fbd20cf62df652fff100c57f20842050\";print(\"PRESERVED_EVIDENCE_ONLY; no guest rerun\")'",
    "artifacts": [
      {
        "path": "sources/vk-offscreen-x64/vk_offscreen_x64.exe",
        "sha256": "aba1c08ccbc7c8f4569c7177cc96032a7baf87c3b255506f1c8f5a452a0a1ae9"
      },
      {
        "path": "logs/vk-offscreen-x64/normal_framebuffer.raw",
        "sha256": "2f69987b28f18023bd1dec8c7b23b925fbd20cf62df652fff100c57f20842050"
      },
      {
        "path": "logs/vk-offscreen-x64/receipt.json",
        "sha256": "c81601ffa4612604b986d87980f29ce5ef3417130ceab35f2c4905009167ac30"
      },
      {
        "path": "scripts/runtime/vk_offscreen_x64/run_probe.py",
        "sha256": "0302f2443ead54f7474ca6fd3df97379651d9bf5b0a65cdd792a1d8c07ff74ce"
      }
    ],
    "runtime_secondary_command": "PYTHONDONTWRITEBYTECODE=1 python3 -I -c 'import sys,time,importlib.util;from pathlib import Path;sys.path.insert(0,str(Path.cwd()));p=Path(\"scripts/runtime/vk_offscreen_x64/run_probe.py\");spec=importlib.util.spec_from_file_location(\"isolated_replay\",p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);m.OUTPUT_DIR=Path(\"logs/status-check/repro-x64-\"+str(time.time_ns())).resolve();m.OUTPUT_DIR.mkdir(parents=True,exist_ok=False);m.PROBE_EXE=Path(\"sources/vk-offscreen-x64/vk_offscreen_x64.exe\").resolve();print(\"REPLAY_PE\",m.PROBE_EXE,\"OUTPUT\",m.OUTPUT_DIR);m.main()'",
    "runtime_secondary_note": "次选实跑：复用无killall的既有x64 runner，显式重定向OUTPUT_DIR与实际PE；ARM64时沿用的内部x64工具/文件名只是标签，架构以实际PE/file/SHA为准。此命令本卡未执行，不新增验证结果；依赖lab sysroot/elfuse/prefix/图形配置，预期运行成功后另核新receipt/raw/rollback。"
  },
  {
    "id": "window",
    "title": "x64真实窗口/消息链独立目录复跑",
    "mode": "新增独立目录实跑",
    "command": "PYTHONDONTWRITEBYTECODE=1 python3 -I scripts/runtime/win_window/run_probe.py \"repro$(date +%Y%m%d%H%M%S)\" runinprefix",
    "expected": "目标exit0，WINDOW_STAGE直到EXIT_OK；默认null显示后端，不能预期宿主屏上Wine窗口；新目录logs/win-window/repro*",
    "artifacts": [
      {
        "path": "sources/win-window-probe/window_x64.exe",
        "sha256": "d6625afe061295e9c02525a15214054c5615eca8db6b5ac348f5c570e7c02365"
      },
      {
        "path": "scripts/runtime/win_window/run_probe.py",
        "sha256": "d9f7865efe8d293350f3fcb7925ce1eb893ab0ee3e0afe1a3ca6d3ec6b8dff67"
      },
      {
        "path": "logs/win-window/baseline/receipt.json",
        "sha256": "8ae572f4f8656730b9821e1315cfecc6d5abbb4c765cfb1275e16917d01a5436"
      }
    ]
  },
  {
    "id": "compat",
    "title": "离线兼容包7项自检与全清单校验",
    "mode": "自检及只读验包（临时文件仅logs/compat-package）",
    "command": "PYTHONDONTWRITEBYTECODE=1 python3 -I scripts/backend/build_compat_package.py test && PYTHONDONTWRITEBYTECODE=1 python3 -I scripts/backend/build_compat_package.py verify",
    "expected": "7 tests OK；inventory_matches=true，8107项（8105文件+2链接）；不写真实Steam",
    "artifacts": [
      {
        "path": "scripts/backend/build_compat_package.py",
        "sha256": "e219baa14b5ab974dd7f990ef79602acfba4c662c7a7a94684f7c15d84a25d8a"
      },
      {
        "path": "logs/compat-package/proton-macos-lab-arm64-diag/SHA256SUMS.json",
        "sha256": "12190148816a97965eca4996e2e679603bc5dbb4e71b27bb019ae9da2a16690d"
      },
      {
        "path": "logs/compat-package/receipt.json",
        "sha256": "564d494e4e731307a8fdb9fc65c6ccd57b0353f79d42456cc943a57f59e73a6d"
      }
    ]
  },
  {
    "id": "inproc",
    "title": "C路线无水印guest同进程读取/合作式UI",
    "mode": "新增独立目录实跑",
    "command": "PYTHONDONTWRITEBYTECODE=1 python3 -I scripts/runtime/inproc_present/run.py \"repro$(date +%Y%m%d%H%M%S)\" on",
    "expected": "目标exit0，INPROC_WINDOW、phase*.png/rgba；自身view像素匹配；无syscall段约3s UI停更；occlusion/人眼可见不保证",
    "artifacts": [
      {
        "path": "sources/elfuse-inproc-present-derived/build/elfuse",
        "sha256": "3b146bbe872aaff1554fe887f419539b8f32747062b66c1afb7f96c661cab926"
      },
      {
        "path": "sources/inproc-present-dylib/present.dylib",
        "sha256": "8605a3b37168bc2fdc0ceb264162b6f13ae08ea18d97f3709d9b7f867c3e3746"
      },
      {
        "path": "scripts/runtime/inproc_present/run.py",
        "sha256": "764a5e93a76e6ade6d535bfc1cfb24feeccae9abcc85c39485cc974681dbab1b"
      },
      {
        "path": "logs/inproc-present/sealedon/receipt.json",
        "sha256": "749b15bbb992d0188d407b9bd0df2f09b9aac14346f642a6513c118e3b7b3c8e"
      }
    ]
  },
  {
    "id": "inproc-wait-negative",
    "title": "C路线永久不ready负测",
    "mode": "新增独立目录实跑",
    "command": "PYTHONDONTWRITEBYTECODE=1 python3 -I scripts/runtime/inproc_present/run.py \"reproWait$(date +%Y%m%d%H%M%S)\" waitnotready",
    "expected": "receipt目标exit88，INPROC_FAIL wait_range_or_ready_timeout；Python索引runner本身可能exit0，不能混淆目标exit",
    "artifacts": [
      {
        "path": "scripts/runtime/inproc_present/run.py",
        "sha256": "764a5e93a76e6ade6d535bfc1cfb24feeccae9abcc85c39485cc974681dbab1b"
      },
      {
        "path": "logs/inproc-present/finalwaitnotready/receipt.json",
        "sha256": "1645ce0720727df063182297e5e02f0a6a006bdbe413028791aee4a93ee6c788"
      }
    ]
  },
  {
    "id": "host-present",
    "title": "文件交接host自身view呈现",
    "mode": "新增独立目录实跑",
    "command": "PYTHONDONTWRITEBYTECODE=1 python3 -I scripts/runtime/host_present/run_spike.py \"repro$(date +%Y%m%d%H%M%S)\"",
    "expected": "符合图形session条件时PASS、4096像素一致；不等于Wine驱动、不申请全局截图权限",
    "artifacts": [
      {
        "path": "sources/host-present-spike/presenter",
        "sha256": "e0bd32e60d93468d9b07dc43862be302b7485a7114b9b810117ba36943deccf0"
      },
      {
        "path": "scripts/runtime/host_present/run_spike.py",
        "sha256": "0d0348929c8ac41e84ca1f24bb867c3c9ee24ef933f56bda90664e5eac8eb765"
      },
      {
        "path": "logs/host-present/trial2/receipt.json",
        "sha256": "1aa3cb0bf1be47d5e365b9dfe90fc422ee7f2c26e33041c5ec4141769f1ba647"
      }
    ]
  },
  {
    "id": "cow-blocked",
    "title": "16KiB/4KiB COW阻塞现存证据",
    "mode": "只读证据复核",
    "command": "python3 -I -c 'import json;from pathlib import Path;print(json.dumps(json.loads(Path(\"logs/ro-section/phase_a_receipt.json\").read_text()),indent=2))'",
    "expected": "打印现存BLOCKED相关分层信息；不运行历史含killall的COW runner",
    "artifacts": [
      {
        "path": "logs/ro-section/phase_a_receipt.json",
        "sha256": "5ac228f31d6c8f1c51e8a042284337a875295be37e9b1afded19458e051484fe"
      },
      {
        "path": "logs/ro-section/production.patch",
        "sha256": "27bb2c82502ac75517bfc900cc6c026e60d201cc3eabefeb7e901a6e3ef4dccf"
      },
      {
        "path": "reports/ro-section.md",
        "sha256": "051a91d0427c50e6f6c166dbe12646f019719225ce48fe5c7026a1fa36552a75"
      }
    ]
  },
  {
    "id": "throughput",
    "title": "只读真实多帧分布索引",
    "mode": "只读证据复核",
    "command": "python3 -I -c 'import json;from pathlib import Path;print(json.dumps(json.loads(Path(\"logs/vk-throughput/summary.json\").read_text()),indent=2))'",
    "expected": "输出既有9组实测，不重新测FPS、不外推游戏",
    "artifacts": [
      {
        "path": "reports/vk-throughput.md",
        "sha256": "b97a54dfe30ca6daacbdb9593a93aa0a62a5295ca8f601933653332a9478b04f"
      },
      {
        "path": "logs/vk-throughput/summary.json",
        "sha256": "505615bbc7d2f7ca08d9da7e91e174829ba2a41e8439881353592132b4d919e9"
      },
      {
        "path": "logs/vk-throughput/slopes.json",
        "sha256": "66389e5043cd4ce6bc3963fb0cab4cc21e52f747f65f4480048f446a845246d8"
      }
    ]
  }
]''')
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--item',choices=[x['id'] for x in ENTRIES])
    parser.add_argument('--json',action='store_true')
    args=parser.parse_args()
    selected=[x for x in ENTRIES if not args.item or x['id']==args.item]
    if args.json:
        print(json.dumps({'workspace':str(LAB),'commands_executed':False,'entries':selected},ensure_ascii=False,indent=2));return
    print('COMMAND INDEX ONLY — no command is executed. Workdir: '+str(LAB))
    for item in selected:
        print('\n['+item['id']+'] '+item['title']+' / '+item['mode'])
        print('COMMAND: '+item['command']);print('EXPECTED: '+item['expected'])
        if item.get('evidence_binding'):print('EVIDENCE_BINDING: '+item['evidence_binding'])
        if item.get('runtime_secondary_command'):
            print('SECONDARY_RUNTIME: '+item['runtime_secondary_command']);print('NOTE: '+item['runtime_secondary_note'])
        for artifact in item['artifacts']:print('SHA256 '+artifact['sha256']+'  '+artifact['path'])
    print('\nHistorical ARM64 offscreen/global-killall runners are NOT replay instructions; see reports/PROJECT-STATUS.md.')
if __name__=='__main__':main()
