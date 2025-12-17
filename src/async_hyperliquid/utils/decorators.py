from typing import TypeVar, Callable, Awaitable
from functools import wraps

T = TypeVar("T")


def private_key_required(
    func: Callable[..., Awaitable[T]],
) -> Callable[..., Awaitable[T]]:
    @wraps(func)
    async def wrapper(self, *args, **kwargs) -> T:
        if self.account.address.lower() != self.address.lower():
            raise ValueError(
                f"Private key is required for account {self.address} in {func.__name__}"
            )
        return await func(self, *args, **kwargs)

    return wrapper
