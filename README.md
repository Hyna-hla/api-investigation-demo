# API Investigation Demo — JSON/API 调试器

给定**期望**与**实际**两份 request/response（JSON），自动做递归 diff，用规则引擎标出异常字段并生成分析报告：哪里坏了、严重程度、期望 vs 实际、以及排查方向。纯 Python 标准库实现。

## Problem

联调/回归一个接口时，常见困境：

- 返回体层层嵌套，字段几十个，肉眼对比 expected / actual 又慢又容易漏；
- 有些差异是致命的（HTTP 500、业务码非 0、关键字段变 null），有些只是正常波动，混在一起无法分级；
- 数字被序列化成字符串、数组长度变化、金额算错、响应变慢——需要统一口径自动识别。

目标：自动完成「请求回放 → 递归 diff → 异常字段分级 → 调查建议」，输出一份能直接驱动排查的报告。

## Approach

```
baseline.json(期望)  +  actual.json(实际)
   │
   ▼
递归 Diff（沿 JSON Path 逐字段比较）
   ├─ missing 字段缺失        ├─ extra 多余字段
   ├─ type_mismatch 类型不一致 ├─ null_unexpected 期望有值却为 null
   ├─ value_changed 取值变化   └─ length_changed 数组长度变化
   │
   ▼
健康规则引擎（独立于 diff）
   ├─ HTTP 状态码必须 2xx（否则 CRITICAL）
   ├─ 业务码 code/errcode 必须为 0（否则 CRITICAL）
   └─ latency/cost/duration 等耗时字段超阈值（默认 500ms）
   │  同路径已存在 HIGH+ 问题时，折叠冗余的低级别 value_changed
   ▼
Markdown 分析报告（判定 PASS/WARN/FAIL + 异常字段表 + 定位思路 + 复现命令）
```

关键设计：**结构对比（diff）**与**语义健康规则（rule engine）**两条线互补——前者回答“和期望差在哪”，后者回答“这次调用本身健不健康”。

## Tools

| 工具 | 用途 |
| --- | --- |
| Python 3 | 递归 diff、规则引擎、报告生成（仅标准库） |
| Git / VS Code | 版本管理与开发 |

## Investigation

运行：

```bash
python src/api_debug.py samples/baseline.json samples/actual.json \
    -o report/api-report.md --json-out report/findings.json --max-latency-ms 500
```

对一次 `/api/v2/checkout` 下单接口的调查：

1. 判定 **FAIL**，共识别 **13 个异常字段**：CRITICAL 2、HIGH 3、MEDIUM 7、LOW 1。
2. 两个致命问题：`status` 由 200 变为 **500**，业务码 `body.code` 由 0 变为 **5001**——服务端整体失败。
3. 高危数据问题：`orderId` 期望订单号却返回 **null**；`user.age` 由数字 **28 变成字符串 "28"**（序列化类型错误）；`user.email` **缺失**。
4. 金额链路异常：商品单价 49.9→59.9、购物车多出 1 个商品、折扣 9.98→0、总价 89.82→138.8，需要核对计价逻辑。
5. 性能与信息泄露：`latency_ms` 120→**1280ms**（超阈值），且多出 `debug` 字段暴露了内部堆栈。
6. 结构化结果同步写入 [`report/findings.json`](report/findings.json)，完整报告见 [`report/api-report.md`](report/api-report.md)。

## Result

- 把“人肉对比两个 JSON”变成一条命令，异常字段按 **CRITICAL/High/Medium/Low** 分级；
- 每条异常都带 **JSON Path、期望、实际、原因、排查方向**，可直接分派给对应负责人；
- 同时产出机器可读的 `findings.json`，方便接入自动化回归 / CI 质量门禁。

## 目录结构

```
api-investigation-demo/
├─ src/api_debug.py          # 调试器主程序
├─ samples/
│  ├─ baseline.json          # 期望的 request/response
│  └─ actual.json            # 实际抓到的 request/response（含多种典型异常）
└─ report/
   ├─ api-report.md          # 自动生成的分析报告
   └─ findings.json          # 结构化异常字段（机器可读）
```
