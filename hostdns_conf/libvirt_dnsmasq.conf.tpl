{% for vnet in libvirt_networks %}
server=/{{ vnet.domain }}/{{ vnet.host_side_ip }}
server=/{{ vnet.reverse_zone }}/{{ vnet.host_side_ip }}
{% endfor %}
