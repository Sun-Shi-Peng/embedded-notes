GPIO输出-LED控制
 GPIO与寄存器
STM32F103ZET6 的 GPIO 端口：PA、PB、PC、PD、PE、PF、PG，每个端口都是 16 个引脚：Pin0～Pin15
每个端口都有一对寄存器：GPIOx_CRL（低配置寄存器）、GPIOxCRH（高配置寄存器）
CRL：控制 Pin0~Pin7（低8个引脚）
CRH：控制 Pin8~Pin15（高8个引脚）
4 位里，靠前 2 位管类型，靠后 2 位管是输入还是输出、输出速度

PA、PB、PC、PD、PE、PF、PG，每一个端口，都独立拥有一套完整的 7 个 32 位寄存器


寄存器

偏移地址

作用

GPIOx_CRL

0x00

低 8 脚（Pin0~7）模式配置

GPIOx_CRH

0x04

高 8 脚（Pin8~15）模式配置

GPIOx_IDR

0x08

输入寄存器，只读，读外部引脚电平

GPIOx_ODR

0x0C

输出寄存器，可读可写，设置输出电平

GPIOx_BSRR

0x10

置位 / 复位寄存器（推荐！原子操作，置 1、清 0，不会有中断冲突）

GPIOx_BRR

0x14

单独复位寄存器，专门用来把 ODR 的 bit 清 0

GPIOx_LCKR

0x18

锁定寄存器，锁住引脚配置，写保护，防止误改
LED点灯
首先在原理图中查看 STM32 与 LED 灯的连接关系，LED1 与 PF8 连接
image.png

配置
3.1 开启GPIO输出
img_v3_02172_f4d5226e-29e9-479d-b857-b9e98552bf7g.jpg

GPIO  output level：设置该引脚的初始电平值，将是输出寄存器的初始值
GPIO mode：常见 Output Push Pull（推挽输出）或者开漏输出
GPIO Pull-ip/Pull-down：表示该引脚进行上拉/下拉
Maximum output speed：设置最大输出速度（选择 Low 即可）
User Label：用户标签

最大输出速度
电平变化是需要时间的，不是陡峭的变化而是有倾斜角度
极端情况下会变成“尖峰”形状，导致抓取信息失败，所以速度不能无限提升
设置速度等级，是满足正确输出信息前提下，通过不同等级来满足不同应用场景
3.2 开启调试
开发板的预留仿真器调试接口是 SWD（Serial Wire Debug）
img_v3_02172_3bc8ddd1-4b8c-4039-9add-85922d9013bg.jpg


注意：
如果没有修改，使用默认的 No Debug，第一次烧录程序是可以的，但是后续烧录程序会烧录失败

DAP VS SWD
DAP Link 是一种调试器硬件，而 SWD 是一种调试通信协议；DAP Link 通过 SWD 协议与目标芯片通信
DAP 全称是 Debug Access Port（调试访问端口），是一个物理仿真器
考试时座位上的同学
SWD 全称是 Serial Wire Debug（串行线调试）
传递纸条的通道+约定好的暗号
3.3 开启外部时钟源
Cycle/Ceramic Resonator 表示选择外部晶振作为 HSE
img_v3_02172_513c61bb-58c1-4347-bd8e-71a738532b1g.jpg

3.4 配置时钟树
开发板上是一个 8MHz 的 HSE 晶振，需要选通 8MHz 晶振作为时钟源，并将系统运行最大频率设置到 72MHz
img_v3_02172_8038b36b-9e44-4910-9493-273b8c5715dg.jpg

3.5 项目路径、工具链配置
选择 Tool Chain 为 MDK-ARM（就是 Keil 这一套开发工具），生成代码
img_v3_02172_c983311f-93bd-4eaa-b7b1-9b48203b73ag.jpg

项目目录结构
image.png

Application/MDK-ARM/ 内部存放了启动文件 startup_stm32f103xe.s
Application/User/Core/包含了
main.c：入口文件，包含 main 函数
stm32f1xx_it.c: 和中断处理相关的逻辑
stm32f1xx_hal_msp.c: msp (MCUSupportPackage)内部包含⼀些硬件层的初始化
Drivers/STM32F1xx_HAL_Driver/ 存放了 HAL 库的源码实现
Drivers/CMSIS 存放了 CMSIS 的源码实现，HAL 库会调用 CMSIS 来完成针对 CPU 的核心操作
CMSIS(绿色图标) 只是表示项目依赖了 CMSIS
点灯代码实现

  /*Configure GPIO pin Output Level */
  HAL_GPIO_WritePin(GPIOF, GPIO_PIN_8, GPIO_PIN_SET);
