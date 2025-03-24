---
title: "{{ title | replace('<i>', '*') | replace('</i>', '*') }}"
aliases:
- {% if shortTitle %}{{ shortTitle }}{% else %}null{% endif %}{% if creators and date %}
- '{% set authlist = authors %}{% set auths = creators | filterby("creatorType", "startswith", "author") %}{% if auths %}{% if auths.length > 2 %}{% set authlist = auths[0].lastName + ' et al.' %}{% elif auths.length == 1 %}{% set authlist = auths[0].lastName %}{% elif auths.length == 2 %}{% set authlist = auths[0].lastName + ' and ' + auths[1].lastName %}{% endif %}{% else %}{% if creators.length > 2 %}{% set authlist = creators[0].lastName + ' et al.' %}{% elif creators.length == 0 %}{% set authlist = title %}{% elif creators.length == 1 %}{% set authlist = creators[0].lastName %}{% elif creators.length == 2 %}{% set authlist = creators[0].lastName + ' and ' + creators[1].lastName %}{% else %}{% set authlist = title %}{% endif %}{% endif %}{{ authlist }} ({{ date | format("YYYY") }}'Z){% endif %}{% if authors %}
authors: {{ authors }}{% else %}creators: {{ creators }}{% endif %}{% if date %}
published: {{ date | format("YYYY-MM-DD[T]HH:mm:ss") }}{% endif %}
accessed: '{{ dateAdded | format("YYYY-MM-DD[T]HH:mm:ss") }}'{% if url %}
url: "{{ url }}"{% endif %}
citation: '{{ bibliography | replace("_", "*") }}'
---

# {% if shortTitle %}{{shortTitle}}{% else %}{{title}}{% endif %}{% if abstractNote %}

{{abstractNote}}{% endif %}

>[!citation]
>{{bibliography | replace("_", "*")}}