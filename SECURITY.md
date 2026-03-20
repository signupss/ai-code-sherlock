# Security Policy

## ⚠️ Never commit API keys

AI Code Sherlock stores all settings (including API keys) in:

```
Windows:  C:\Users\<user>\.ai_code_sherlock\settings.json
Linux:    ~/.ai_code_sherlock/settings.json
macOS:    ~/.ai_code_sherlock/settings.json
```

This folder is **outside the repository** and is **never committed to Git**.

## Before pushing to GitHub — checklist

- [ ] No `settings.json` in the repo (check with `git status`)
- [ ] No `.env` file with keys
- [ ] No hardcoded `api_key = "sk-..."` in any source file
- [ ] `.sherlock_versions/` is in `.gitignore`
- [ ] Run `git log --all --full-history -- "*.json"` to confirm no keys in history

## If you accidentally committed a key

1. Revoke the key immediately in the provider dashboard
2. Remove it from history:
   ```bash
   git filter-branch --force --index-filter \
     "git rm --cached --ignore-unmatch path/to/file_with_key" \
     --prune-empty --tag-name-filter cat -- --all
   git push origin --force --all
   ```
3. Or use [BFG Repo-Cleaner](https://rtyley.github.io/bfg-repo-cleaner/) (faster)

## Reporting vulnerabilities

Please open a [GitHub Issue](https://github.com/signupss/ai-code-sherlock/issues) marked `[Security]`.
