# 运维：机器、git、账号、备份与清理

> 2026-11-06 建立。返回 [README](../../README.md) ｜ 入口 [AGENTS.md](../../AGENTS.md)

## 一、机器与访问

| 项 | 值 |
|---|---|
| 主机名 | `DESKTOP-E72MK8D`（3D 打印电脑） |
| 局域网地址 | `192.168.68.44`，SSH 别名 `3dprint`（本机 `~/.ssh/config`） |
| 账户 | `000`（管理员组），OpenSSH_for_Windows_9.5p1 |
| 项目目录 | `D:\HA1\PJ1` |
| 磁盘 | D: 138.5GB，2026-11-06 剩余 43.9GB |

外网可用（`curl https://github.com` 返回 200），winget 源数据损坏（`0x8a15000f`），
所以 git 是用便携版直接装的，没走 winget。

## 二、git（2026-11-06 装的）

```bat
:: 位置：便携版，不在 C:\Program Files
D:\Tools\PortableGit\cmd\git.exe --version   :: git version 2.56.0.windows.4

:: 已把 D:\Tools\PortableGit\cmd 追加到「用户级」PATH（没有动系统 PATH）
:: 新开的会话直接可用；装之前已登录的窗口需要重开
```

仓库信息：

- 分支 `main`，提交身份是仓库级配置 `PJ1 <pj1@local>`（不是全局）
- 基线提交 `5e78bd9`（2026-11-06）：2.2.8 的未入库代码改动 + 文档治理一并入库
- 此前 2.2.8 的代码改动一直停留在工作区没提交，`dist/` 从来不入库

常用：

```bat
cd /d D:\HA1\PJ1
git status --short
git log --oneline -5
git add -A & git commit -m "说明"
```

⚠️ 提交信息含中文时，用 `git commit -F 文件`（文件存 UTF-8）比 `-m` 稳妥，
避免经过 cmd 的代码页转换变成乱码。

## 三、账户 `000` 是空密码（已知风险，**不修**）

| 项 | 情况 |
|---|---|
| 现状 | `PasswordRequired=False`（空密码），`LimitBlankPasswordUse=1` |
| 为什么不动 | 空密码很可能是为「开机自动登录」设的，改密码会让自动登录失效，影响产线开机即用 |
| 实际影响 | 空密码只拦 NTLM / 交互式网络登录，**拦不住 publickey**；实测公钥登录正常 |
| 已做的收敛 | 防火墙 `OpenSSH-Server-In-TCP` 的 RemoteAddress 已限制为 `192.168.68.0/24`，只有局域网可达 |
| 残留风险 | 同一局域网内、且拿到私钥的机器可以无密码登录；机器物理接触者可本地登录 |
| 若将来要修 | 设密码 → 同时改自动登录（`control userpasswords2` 或 `Autologon`）→ 验证 SSH 公钥仍可用 |

## 四、备份与清理

### 一次性备份

- `backup_docs_20261106/`：文档治理前的 README / CHANGELOG / docs 全量
- 已在 `.gitignore` 里排除（`backup_docs_*/`），确认无误后可整个删掉

### 归档区（`D:\HA1\archive\`，在项目外，不进版本库）

| 目录 | 内容 | 恢复方式 |
|---|---|---|
| `output_stl_2026Q1\` | 78 个 2026 年 1~3 月的批次（目录时间戳都是 2026-03-27 21:49，从旧系统一次性迁入的） | 把需要的批次目录移回 `D:\HA1\PJ1\data\output_stl\` 即可，文件名与层级不变 |
| `releases\` | 历史发布包（当前为空） | — |

### 清理规则

| 对象 | 规则 |
|---|---|
| `build/` | PyInstaller 中间产物，可随时整个删掉，下次打包自动重建 |
| `dist/vX.Y.Z/` | 只保留当前版本目录；每个版本自带一份约 48MB 便携 OpenSCAD |
| `dist/legacy/` | 旧版 PJ1Program 包，同事还在用，别删 |
| `data/output_stl/` | 业务数据，**不删除**；超过约 6 个月的批次移到 `D:\HA1\archive\output_stl_<年季>\` |
| `.cache/` | 一次性调试脚本与实测截图，可删（但里面有 `analyze_stl.py`、`measure.py` 等可复用脚本，删前看一眼） |

## 五、教训

清理发布目录前**先确认要保留的包已经移到 `archive\releases\` 并核对文件存在**，
再删目录。2026-11-06 就是先 move（失败）后删，把 `StampGen-2.2.7-win64.zip` 一起删掉了。
过程记录见 `CHANGELOG.md` 的「未发布 — 文档治理」条目。
