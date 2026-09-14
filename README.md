# DeCodeMoMo

离线候选生成实验项目。它只在本地从显式提供的线索生成候选字符串，不连接账户、钥匙串、备忘录或任何在线验证服务，也不会自动提交尝试。

## 第二期运行

把个人线索逐行放在本地 `personal_hints.local.txt` 中。该文件已加入 `.gitignore`，不会进入版本库。

```bash
python3 toy_candidate_lab.py \
  --hints-file personal_hints.local.txt \
  --exclude toy_candidates_v1.txt \
  --output toy_candidates_v2.txt \
  --limit 50000
```

输出文件每行只有一个 ASCII 候选值，不包含中文、评分或规则说明。第一期候选会被精确排除，第二期结果写入新的文件，避免覆盖基线。

## 测试

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile toy_candidate_lab.py tests/test_toy_candidate_lab.py
```

## 安全边界

本项目适合对自己拥有的离线数据做候选整理和合成实验。不要把个人线索、候选列表或密码提交到公共仓库，也不要对在线服务自动化尝试。
