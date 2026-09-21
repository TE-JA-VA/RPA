# 이 창에서만 JDK 21 을 앞세운다. 시스템 PATH 는 건드리지 않는다.
# 쓰는 법:  cd D:\AX\RPA\firebase; . .\emu_env.ps1
$env:JAVA_HOME = "$env:USERPROFILE\.devtools\jdk-21"
$env:Path = "$env:JAVA_HOME\bin;" + $env:Path
