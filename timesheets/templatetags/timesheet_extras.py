from django import template

register = template.Library()


@register.filter
def get_item(dictionary, key):
    return dictionary.get(key, '')


@register.filter
def search_key(person):
    """Lowercased 'firstname lastname employeeid' for a member-grid search box."""
    return f"{person.firstname} {person.lastname} {person.employeeid}".lower()
