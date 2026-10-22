from django import template


register = template.Library()


@register.simple_tag
def page_breadcrumbs(*items):
    """Build ordered label/URL pairs; an incomplete pair is a template error."""
    return [
        {'label': label, 'url': url} for label, url in zip(items[::2], items[1::2], strict=True)
    ]
