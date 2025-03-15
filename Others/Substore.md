# 以下为Substore部署教程
## 基础版
- 前提条件：
一个可以使用的docker，至少120mb的docker空间
或者代理软件内置Substore支持也可以使用
如果你已满足上述条件那么可以进行下一步
## 安装Substore,以openwrt平台为例
打开docker输入以下命令
```
docker run -it -d \
  --name sub-store \
  --restart=always \
  --net=host \
  -e "SUB_STORE_CRON=55 23 * * *" \
  -e "SUB_STORE_FRONTEND_BACKEND_PATH=/CKg2abstVnOeRpm1aB4G" \
  -v /etc/sub-store:/opt/app/data \
  xream/sub-store
```
等待安装完成
### 后台访问
比如路由器网段为192.168.2.0/24
那么如果你要访问Substore后台则须将x改为与路由器同一网段的2将y改为部署substore的openwrt设备的最后一位ip
访问参考代码
```
http://192.168.x.y:3001/subs?api=http://192.168.x.y:3001/CKg2absthskxudnm
```
- 其中这一段CKg2absthskxudnm为Substore访问的安全路径或者说是密码，在公共vps上部署请勿将该段设置得过于简单
- [在线密码生成网站](https://1password.com/zh-cn/password-generator)
## Substore设置部分
打开后台后点击第二页文件管理，创建文件
#### 1.名称部分可自定义但必填
#### 2.选填：显示名称，备注，图标链接，查询流量信息订阅链接，查询流量信息 User-Agent，User-Agent，代理/策略，合并来源
#### 3.关闭，启用下载(文件名为显示名称)
#### 4.类型选择文件，来源选择远程
## 链接部分
标准版填入
```
https://raw.githubusercontent.com/Lanlan13-14/Rules/refs/heads/main/configfull.yaml#noCache
```
NoAd版填入
```
https://raw.githubusercontent.com/Lanlan13-14/Rules/refs/heads/main/configfull_NoAd.yaml#noCache
```
Stash版填入
```
https://raw.githubusercontent.com/Lanlan13-14/Rules/refs/heads/main/configfull_Stash.yaml#noCache
```
## 脚本部分
### 机场链接自动填写
1.创建脚本操作选择脚本，删除原有全部内容
如果要自动填“订阅链接1”则输入
```
$content = $content.replace(/订阅链接1/g, '此处填写订阅链接');
```
以此类推，替换2/3就把（订阅链接1）替换为（订阅链接2）再贴上订阅
### 添加机场备注
```
$content = $content.replace(/机场名称1/g, '此处填写机场备注');
```
替换2/3同理
### 修改webUi面板代理提供者部分显示的名称
```
$content = $content.replace(/Airport_01/g, '此处填写机场备注');
```
### 自动策略组排除指定机场/节点，该功能依赖第二步添加机场备注
我在自动策略组都加入了类似于The_US_automation的无关过滤词供各位替换
比如我想要在美国自动里排除带有“凤凰城”名字的节点那么我只需在脚本处添加如下脚本
```
$content = $content.replace(/The_US_automation/g, '凤凰城');
```
需要在自建/家宽节点自定义过滤的使用以下代码，以过滤HGC为例
```
$content = $content.replace(/The_house/g, 'hgc');
```
这些设置完成后便可以点击保存，复制链接，在同一局域网内如同使用订阅一样使用

### 实在不会的这里提供部署事例
#### nikki订阅要选择本地
![Substore 部署示例1](https://raw.githubusercontent.com/Lanlan13-14/Rules/refs/heads/main/Others/Substore01.jpg)
![Substore 部署示例2](https://raw.githubusercontent.com/Lanlan13-14/Rules/refs/heads/main/Others/Substore02.jpg)
![Substore 部署示例3](https://raw.githubusercontent.com/Lanlan13-14/Rules/refs/heads/main/Others/Substore03.jpg)

## 高级篇
#### 部署同上，请确保Substore版本已为最新版
使用教程如下
- 1 新建文件选择mihomo覆写如图
![Substore高级01](https://raw.githubusercontent.com/Lanlan13-14/Rules/refs/heads/main/Others/Substore%E9%AB%98%E7%BA%A701.jpg)
- 2 新建后名称自定义一个不重复的
- 3 类型-选择mihomo配置
- 4 来源-选择无
- 5 若想自定义配置名称那么在显示名称那里输入并开启启用下载，如图
![Substore高级02](https://raw.githubusercontent.com/Lanlan13-14/Rules/refs/heads/main/Others/Substore%E9%AB%98%E7%BA%A702.png)
- 6 其余选项个人需要填写
## 链接部分（🔗链接一定要放在第一个脚本处）
- 1 新建一个脚本
标准版填入
```
https://raw.githubusercontent.com/Lanlan13-14/Rules/refs/heads/main/configfull.yaml#noCache
```
NoAd版填入
```
https://raw.githubusercontent.com/Lanlan13-14/Rules/refs/heads/main/configfull_NoAd.yaml#noCache
```
Stash版填入
```
https://raw.githubusercontent.com/Lanlan13-14/Rules/refs/heads/main/configfull_Stash.yaml#noCache
```
- 2 新建一个脚本以替换订阅及名称所需代码与基础篇一致包括自定义过滤部分

-  若仅有一个订阅链接那么只需要使用最简单的yaml覆写即可代码如下

```yaml
proxy-providers!:
  Airprot01:
    type: http
    interval: 86400
    health-check:
      enable: true
      url: 'http://captive.apple.com/'
      interval: 300
    proxy: "\U0001F7E2 直连"
    url: >-
      订阅链接替换
    override:
      additional-prefix: '[机场名称]'
      skip-cert-verify: true
      udp: true
  Linkcube:
    type: http
    interval: 86400
    health-check:
      enable: true
      url: 'http://captive.apple.com/'
      interval: 300
    proxy: "\U0001F7E2 直连"
    url: >-
      订阅链接替换
    override:
      additional-prefix: '[机场名称]'
      skip-cert-verify: true
      udp: true

#### 添加自定义国家分组/策略组，以韩国为例，新建脚本输入以下内容
```
function main(config) {
  // 确保 `proxy-groups` 存在
  if (!config["proxy-groups"]) {
    config["proxy-groups"] = [];
  }

  // 找到 "欧洲节点" 的位置
  const euIndex = config["proxy-groups"].findIndex(group => group.name === "欧洲节点");

  // 定义 "韩国节点" 策略组
  const krGroup = {
    name: "韩国节点",
    type: "select",
    "include-all": true,
    tolerance: 20,
    interval: 300,
    filter: "(?i)(韩|🇰🇷|kr|Korea)",
    "exclude-filter": "(?i)(直连|群|邀请|返利|循环|官网|客服|网站|网址|获取|订阅|流量|到期|机场|下次|版本|官址|备用|过期|已用|联系|邮箱|工单|贩卖|通知|倒卖|防止|国内|地址|频道|无法|说明|使用|提示|特别|访问|支持|教程|关注|更新|作者|加入|USE|USED|TOTAL|EXPIRE|EMAIL|Panel|Channel|Author|traffic)",
    icon: "https://raw.githubusercontent.com/Lanlan13-14/Rules/refs/heads/main/icon/Korea.png"
  };

  // 插入到 "欧洲节点" 之后
  if (euIndex !== -1) {
    config["proxy-groups"].splice(euIndex + 1, 0, krGroup);
  } else {
    // 如果找不到 "欧洲节点"，则添加到末尾
    config["proxy-groups"].push(krGroup);
  }

  return config;
}
```
该脚本会自动在欧洲节点后添加一个名为韩国节点的策略组，
若要在没个节点选择里面都能选择该组那么则需使用如下代码
- 1 所添加的不在proxy-group内
```
function main(config) {
  // 确保 `pr` 这个对象存在
  if (config["pr"] && Array.isArray(config["pr"].proxies)) {
    // 找到 "欧洲节点" 在 proxies 里的位置
    const euIndex = config["pr"].proxies.indexOf("欧洲节点");

    // 如果找到了 "欧洲节点"，就在它后面插入 "韩国节点"
    if (euIndex !== -1) {
      config["pr"].proxies.splice(euIndex + 1, 0, "韩国节点");
    }
  }

  return config;
}
```
- 2 所添加的在proxy-group内
```
function main(config) {
  // 确保 `proxy-groups` 存在
  if (!config["proxy-groups"]) {
    config["proxy-groups"] = [];
  }

  // 找到 "节点选择" 组
  const nodeSelectGroup = config["proxy-groups"].find(group => group.name === "节点选择");

  if (nodeSelectGroup && Array.isArray(nodeSelectGroup.proxies)) {
    // 找到 "欧洲节点" 在 proxies 里的位置
    const euIndex = nodeSelectGroup.proxies.indexOf("欧洲节点");

    // 如果找到了 "欧洲节点"，就在它后面插入 "韩国节点"
    if (euIndex !== -1) {
      nodeSelectGroup.proxies.splice(euIndex + 1, 0, "韩国节点");
    }
  }

  return config;
}
```

以此类推如果你想再添加照着上方代码修改即可，添加其他策略组也是如此操作即可
#### 添加自建节点以添加ss2022节点回家为例使用如下代码，其余代理协议需要其他配置可自行参照[mihomo官方文档](https://wiki.metacubex.one)填入
```
function main(config) {
  // 确保 `proxies` 存在
  if (!config["proxies"]) {
    config["proxies"] = [];
  }

  // 定义自建节点
  const homeNode = {
    name: "🏠 home",
    type: "ss",
    server: "写入你的域名或ip",
    port: 这里写入端口,
    cipher: "这里写入你的加密方式",
    password: "这里写入密码",
    tfo: false
  };

  // 直接添加到 `proxies`
  config["proxies"].push(homeNode);

  return config;
}
```
#### 添加自定义规则
仍然以添加backhome为例输入以下代码
```
function main(config) {
  // 确保 `rule-providers` 存在
  if (!config["rule-providers"]) {
    config["rule-providers"] = {};
  }

  // 添加新的 rule-provider
  config["rule-providers"]["localip192.168.31.0"] = {
    type: "http",
    interval: 86400,
    behavior: "classical",
    format: "yaml",
    url: "https://raw.githubusercontent.com/Lanlan13-14/Rules/refs/heads/main/rules/IP/localip_192.168.31.0.yaml",
  };

  // 确保 `rules` 存在
  if (!config["rules"]) {
    config["rules"] = [];
  }

  // 添加规则
  config["rules"].unshift("RULE-SET,localip192.168.31.0,Back_store,no-resolve");

  return config;
}
```
该规则将会在rule-providers里添加新规则源 "localip192.168.31.0"

在 rules 中插入新的规则 "RULE-SET,localip192.168.31.0,Back_store,no-resolve"
其余以此类推，规则写法部分参考[mihomo官方文档](https://wiki.metacubex.one)

#### 最后预览符合预期后保存复制链接即可，如果想要在外面也能更新那么只需要一个反代+域名+ssl证书即可实现，反代地址填入刚刚复制的链接即可

### 若能力有限建议使用[ChatGPT](https://chatgpt.com)复制代码让他按照你的要求修改
