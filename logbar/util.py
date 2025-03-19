from typing import Iterable, Optional, Union

# simplify user usage so instead of this: pb(range(10))
# they use: pb(10)
def auto_iterable(input) -> Optional[Iterable]:
    if isinstance(input, Iterable):
        return input

    if isinstance(input, int):
        return range(input)

    # when you iterate dict/sets, 99% of the time you want to call items()
    # and for loop k,v
    if isinstance(input, (dict, set)):
        return input.items()

    return None

