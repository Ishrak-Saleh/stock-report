"""Bundle variants (SOP section 3, should): one sale of "Buy 2 Get 2" is 4 units. Pure function."""


def units_sold(quantity: int, variant: str, bundle_map: dict[str, int]) -> int:
    """Units that left the warehouse for `quantity` sales of a variant. An empty variant means single units."""
    if not variant:
        return quantity
    if variant not in bundle_map:
        raise ValueError(f"'{variant}' is not a bundle for this product.")
    return quantity * bundle_map[variant]
