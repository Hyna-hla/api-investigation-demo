# JSON / API 调试分析报告

> 由 `api_debug.py` 自动生成于 2026-09-09 11:40:05

## 1. 结论

**判定：FAIL — 存在需立即处理的异常字段**

| 严重级别 | 数量 |
| --- | ---: |
| CRITICAL | 2 |
| HIGH | 3 |
| MEDIUM | 7 |
| LOW | 1 |

## 2. 请求回放

```json
{
  "method": "POST",
  "path": "/api/v2/checkout",
  "headers": {
    "content-type": "application/json",
    "authorization": "Bearer ***"
  },
  "body": {
    "user_id": 10086,
    "sku_list": [
      {
        "sku": "A-100",
        "qty": 2
      }
    ],
    "coupon": "NEW10"
  }
}
```

## 3. 异常字段清单

| 严重级别 | 字段路径 | 异常类型 | 期望值 | 实际值 | 说明 |
| --- | --- | --- | --- | --- | --- |
| CRITICAL | `$.status` | bad_http_status | 2xx | 500 | HTTP 状态码 500 非 2xx，请求未成功 |
| CRITICAL | `$.body.code` | biz_error | 0 | 5001 | 业务错误码为 5001(非 0)，接口返回业务失败 |
| HIGH | `$.body.data.orderId` | null_unexpected | ORD-20260909-0001 | null | 期望有值，实际返回 null |
| HIGH | `$.body.data.user.age` | type_mismatch | 28 | 28 | 期望类型 int，实际 str |
| HIGH | `$.body.data.user.email` | missing | zs@example.com | null | 期望中存在但响应缺失该字段 |
| MEDIUM | `$.latency_ms` | value_changed | 120 | 1280 | 字段取值与期望不一致 |
| MEDIUM | `$.body.data.items` | length_changed | 1 | 2 | 数组长度由 1 变为 2 |
| MEDIUM | `$.body.data.items[0].price` | value_changed | 49.9 | 59.9 | 数值偏离期望值，超出容差 |
| MEDIUM | `$.body.data.items[0].subtotal` | value_changed | 99.8 | 119.8 | 数值偏离期望值，超出容差 |
| MEDIUM | `$.body.data.discount` | value_changed | 9.98 | 0 | 数值偏离期望值，超出容差 |
| MEDIUM | `$.body.data.total` | value_changed | 89.82 | 138.8 | 数值偏离期望值，超出容差 |
| MEDIUM | `$.latency_ms` | slow | <= 500 | 1280 | 耗时 1280ms 超过阈值 500ms |
| LOW | `$.body.debug` | extra | null | stacktrace exposed at OrderService.calc | 响应多出未约定字段(确认是否需要) |

## 4. 调查与定位思路

- `$.status` 表明服务端返回失败：先看服务端同时段日志与该请求参数，确认是参数问题还是下游依赖故障。
- `$.body.code` 表明服务端返回失败：先看服务端同时段日志与该请求参数，确认是参数问题还是下游依赖故障。
- 期望有值却为 null：排查上游数据是否缺失、外键关联是否断链。
- 类型不一致：常见于数字被序列化成字符串、对象被错误地包了一层数组，沿序列化层向上排查。
- 字段缺失：确认接口版本是否变更、序列化是否忽略了空值、或该分支是否提前 return。
- 取值/长度变化：判断是正常业务波动还是缺陷；若为金额/数量字段需重点核对计算逻辑。
- 耗时超过 500ms：检查慢查询、下游调用与是否命中缓存。
- 多出字段：确认是否为新版本新增，避免客户端严格解析时报错。

## 5. 复现命令

```bash
python api_debug.py samples/baseline.json samples/actual.json --max-latency-ms 500
```
