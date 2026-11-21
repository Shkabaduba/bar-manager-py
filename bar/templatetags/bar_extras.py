from django import template

register = template.Library()

_DRINK_ART_RULES = (
    (
        (
            "negroni",
            "campari",
            "spritz",
            "bloody",
            "cosmo",
            "ruby",
            "berry",
        ),
        "img/cocktail_negroni.png",
    ),
    (
        (
            "whiskey",
            "whisky",
            "sour",
            "bourbon",
            "old fashioned",
            "manhattan",
            "amber",
        ),
        "img/cocktail_whiskey_sour.png",
    ),
    (
        (
            "lemonade",
            "mint",
            "mojito",
            "lime",
            "virgin",
            "fresh",
            "tonic",
            "citrus",
        ),
        "img/cocktail_lemonade.png",
    ),
)


@register.filter
def drink_pixel_art(drink) -> str:
    """Return a local static pixel-art image path for a Drink instance."""
    if not drink:
        return "img/cocktail_classic.png"

    drink_name = str(getattr(drink, "name", "") or "").lower()
    for keywords, asset_path in _DRINK_ART_RULES:
        if any(keyword in drink_name for keyword in keywords):
            return asset_path

    state = getattr(drink, "_state", None)
    fields_cache = getattr(state, "fields_cache", {}) if state else {}
    cached_category = fields_cache.get("category")
    if cached_category is not None:
        if not cached_category.is_alcohol:
            return "img/cocktail_lemonade.png"
        category_title = str(getattr(cached_category, "name", "")).lower()
        if "signature" in category_title:
            return "img/cocktail_signature.png"

    drink_pk = getattr(drink, "pk", 0) or 0
    if drink_pk % 2 == 1:
        return "img/cocktail_signature.png"
    return "img/cocktail_classic.png"
