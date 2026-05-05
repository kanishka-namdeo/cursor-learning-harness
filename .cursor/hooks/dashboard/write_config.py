import pathlib
p = pathlib.Path(r"C:\Users\kanis\.streamlit\config.toml")
content = """[browser]
collectUsageStats = false

[server]
headless = true

[general]
email = "kanishkanamdeo@hotmail.com"
"""
p.write_text(content, encoding="utf-8")
print("Config written successfully")
print(p.read_text(encoding="utf-8"))
