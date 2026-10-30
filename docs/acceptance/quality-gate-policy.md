# Quality Gate 策略说明

- `passed`：所有此 profile 所需的确定性检查都通过，且没有缺失的必需外部证据。
- `blocked`：检测到阻断问题，例如配置策略违规、可疑秘密字符串或制品摘要不一致。
- `incomplete`：必需的外部工具或证据尚未执行/提供；该状态不能发布。
- `not_run`：某个非必需工具未执行；必须保留在报告内，不得改写为 passed。

当前样例将 development profile 的外部扫描设为可选警告；production profile 要求真实 Trivy/Gitleaks 执行证据。内置检查不等于完整 SAST、SCA、容器扫描或法律许可审查。
