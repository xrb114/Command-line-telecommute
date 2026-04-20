# Corporate remote

Corporate remote
- 这是一个 类似反向代理的程序，已经过部分检测，3/70 的被检测的概率，因为这个的逻辑十分的简单，都是正常操作，把文本传到客户端，然后客户端本地执行传过来的命令，所以说被检测到的比较少。
- server端用法：python3 main.py server
- 客户端用法：直接编辑好端口打包成exe进行运行
- 打包命令:nuitka --standalone --onefile --windows-disable-console client.py
- 拥有截图功能
- 支持基础远程文件管理（上传 / 下载）

![image.png](images/image.png)
命令在连接后有提示，可以屏幕截图和调用摄像头

## 新增：远程文件管理

在 server 端连接某台设备后，可在设备会话内执行：

- `download <远程路径> [本地保存路径]`
  - 作用：从客户端机器下载文件到 server 机器
  - 示例：`download /home/student/report.pdf ./downloads/report.pdf`
- `upload <本地路径> [远程保存路径]`
  - 作用：把 server 机器上的文件上传到客户端机器
  - 示例：`upload ./tools/helper.exe C:\\Users\\Public\\helper.exe`

![received_screenshot.jpg](images/1bafdea80207047e4951ab1dfbfd347.png)
![received_screenshot.jpg](images/imag.jpg)
