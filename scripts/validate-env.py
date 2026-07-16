from platform_api.config import get_settings

print(get_settings().model_dump_json())
