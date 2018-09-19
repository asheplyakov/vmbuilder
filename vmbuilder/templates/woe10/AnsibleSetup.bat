
rem enable WinRM firewall
netsh advfirewall firewall set rule group="remote administration" new enable=yes
netsh firewall add portopening TCP 5985 "Port 5985 (WinRM via HTTP)"
{% if http_proxy %}
netsh winhttp set proxy "{{ http_proxy.split('http://', 1)[-1] }}"
{% endif %}

powershell.exe -Command "Set-ExecutionPolicy -ExecutionPolicy Unrestricted -Force"
rem unencrypted powershell remoting can't be enabled on "Public" connections
rem Loop through all network connections and change "Public" ones to "Private"
powershell.exe -File a:\fixnetwork.ps1

rem upgrade powershell and .NET
powershell.exe -File a:\Upgrade-PowerShell.ps1  -Version 5.1 -Verbose -Username Administrator -Password {{ admin_password }} -Callback "{{ web_callback_url }}"
