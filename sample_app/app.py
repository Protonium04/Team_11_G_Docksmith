import os

print("Hello from bundled Python app.")
print("Runtime APP_MESSAGE =", os.getenv("APP_MESSAGE", "<unset>"))
