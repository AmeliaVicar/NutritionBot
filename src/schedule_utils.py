def staggered_daily_time(
    index: int,
    *,
    base_hour: int = 20,
    base_minute: int = 0,
    step_minutes: int = 3,
) -> tuple[int, int]:
    if index < 0:
        raise ValueError("index must be >= 0")
    if not 0 <= base_hour <= 23:
        raise ValueError("base_hour must be in range 0..23")
    if not 0 <= base_minute <= 59:
        raise ValueError("base_minute must be in range 0..59")
    if step_minutes < 0:
        raise ValueError("step_minutes must be >= 0")

    total_minutes = (base_hour * 60) + base_minute + (index * step_minutes)
    hour = (total_minutes // 60) % 24
    minute = total_minutes % 60
    return hour, minute
