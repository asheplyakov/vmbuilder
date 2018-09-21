
set ADMINPW={{ admin_password }}

rem enable WinRM firewall
netsh advfirewall firewall set rule group="remote administration" new enable=yes
netsh advfirewall firewall add rule name="Port 5985 (WinRM via HTTP)" dir=in action=allow protocol=TCP localport=5985 profile=any

{% if http_proxy %}
netsh winhttp set proxy "{{ http_proxy.split('http://', 1)[-1] }}"
{% endif %}

rem upgrade powershell and .NET
powershell.exe -Command "Set-ExecutionPolicy -ExecutionPolicy Unrestricted -Force"
powershell.exe -File a:\Upgrade-PowerShell.ps1  -Version 5.1 -Verbose -Username Administrator -Password %ADMINPW% -Callback "{{ web_callback_url }}"
