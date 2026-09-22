import re
from typing import List, Tuple, Optional, Union, Iterable, Set


class MessageFilter:
    """本地规则过滤器，优先于 TypeSafe AI 执行"""

    COMMAND_PREFIXES: Tuple[str, ...] = ("//", "/", "#", "!", "！", "。", ".", "／")

    # 常见纯媒体/表情/代码消息占位符或标签
    MEDIA_PLACEHOLDER_REGEX = re.compile(
        r"^(\[(图片|动画表情|表情|语音|视频|文件|分享|xml代码|json代码|合并转发)\]|"
        r"\[CQ:(image|record|video|share|forward|xml|json)[^\]]*\]|\s)+$",
        re.IGNORECASE,
    )

    @classmethod
    def is_pure_media_message(cls, text: str) -> bool:
        """判断是否为纯媒体/纯表情/CQ码消息（无实际有效对话文本）"""
        if not text:
            return True
        stripped = text.strip()
        if not stripped:
            return True
        return bool(cls.MEDIA_PLACEHOLDER_REGEX.fullmatch(stripped))

    @staticmethod
    def check_whitelist_blacklist(
        session_id: Union[str, Iterable[str]],
        user_id: str,
        filter_mode: str,
        session_whitelist: Union[List[str], Set[str]],
        session_blacklist: Union[List[str], Set[str]],
        user_whitelist: Union[List[str], Set[str]],
        user_blacklist: Union[List[str], Set[str]],
    ) -> Tuple[bool, Optional[str]]:
        """
        检查黑白名单，优先级：黑名单 > 白名单 > 普通规则
        支持传入单个 session_id 或多个候选会话标识（如 [group_id, session_id, umo]）。
        """
        # 提取会话候选标识集合
        if isinstance(session_id, str):
            session_candidates = {session_id.strip()} if session_id.strip() else set()
        elif isinstance(session_id, set):
            session_candidates = session_id
        else:
            session_candidates = {str(x).strip() for x in session_id if str(x).strip()}

        user_id_str = str(user_id or "").strip()

        # 转换为 set（若调用方已传入 set 则直接复用，避免重复构建）
        session_bl_set = (
            session_blacklist
            if isinstance(session_blacklist, set)
            else {str(x).strip() for x in session_blacklist if str(x).strip()}
        )
        user_bl_set = (
            user_blacklist
            if isinstance(user_blacklist, set)
            else {str(x).strip() for x in user_blacklist if str(x).strip()}
        )
        session_wl_set = (
            session_whitelist
            if isinstance(session_whitelist, set)
            else {str(x).strip() for x in session_whitelist if str(x).strip()}
        )
        user_wl_set = (
            user_whitelist
            if isinstance(user_whitelist, set)
            else {str(x).strip() for x in user_whitelist if str(x).strip()}
        )

        # 1. 黑名单检查（绝对优先）
        matched_session_bl = session_candidates.intersection(session_bl_set)
        if matched_session_bl:
            return False, f"session_in_blacklist({next(iter(matched_session_bl))})"

        if user_id_str and user_id_str in user_bl_set:
            return False, f"user_in_blacklist({user_id_str})"

        # 归一化 filter_mode
        mode = str(filter_mode).strip().lower()
        if "all" in mode or "全" in mode or mode == "blacklist_only" or "仅黑" in mode:
            return True, None

        if "whitelist" in mode or "仅白" in mode or "both" in mode or "并用" in mode:
            # 只要命中会话白名单或用户白名单任意一个即视为在白名单中
            in_session_wl = (
                bool(session_candidates.intersection(session_wl_set))
                if session_wl_set
                else False
            )
            in_user_wl = (
                (user_id_str in user_wl_set)
                if (user_id_str and user_wl_set)
                else False
            )

            if not session_wl_set and not user_wl_set:
                return False, "whitelist_empty_mode_restrictive"

            if in_session_wl or in_user_wl:
                return True, None
            return False, "not_in_whitelist"

        return True, None

    @staticmethod
    def check_length(
        text: str, min_len: int = 2, max_len: int = 2000
    ) -> Tuple[bool, Optional[str]]:
        """检查消息文本长度是否在合理区间"""
        length = len(text.strip())
        if length < min_len:
            return False, f"message_too_short({length}<{min_len})"
        if max_len > 0 and length > max_len:
            return False, f"message_too_long({length}>{max_len})"
        return True, None

    @classmethod
    def is_command_message(cls, text: str) -> bool:
        """判断是否为指令类消息"""
        stripped = text.strip()
        if not stripped:
            return False
        return any(stripped.startswith(p) for p in cls.COMMAND_PREFIXES)

    @staticmethod
    def is_bot_name_mentioned(text: str, aliases: List[str]) -> bool:
        """检测消息文本中是否明确提到了机器人名称或别名"""
        if not aliases or not text:
            return False
        lowered = text.lower()
        for alias in aliases:
            if alias and alias.lower() in lowered:
                return True
        return False

    @staticmethod
    def matches_keywords(text: str, keywords: List[str]) -> bool:
        """检查文本是否包含关键词列表中的任一词"""
        if not text or not keywords:
            return False
        for kw in keywords:
            if kw and kw in text:
                return True
        return False

    @staticmethod
    def matches_regex(text: str, pattern: Union[str, re.Pattern]) -> bool:
        """检查文本是否匹配指定的正则表达式（支持预编译 Pattern 或字符串）"""
        if not text or not pattern:
            return False
        try:
            if isinstance(pattern, re.Pattern):
                return bool(pattern.search(text))
            p_str = str(pattern).strip()
            if not p_str:
                return False
            return bool(re.search(p_str, text, re.IGNORECASE))
        except re.error:
            return False

    @staticmethod
    def is_explicitly_at_bot(event, bot_aliases: Optional[List[str]] = None) -> bool:
        """
        精确判断消息是否真实显式 @了机器人 或 回复了机器人的消息。
        注意：
        1. 不能直接使用 event.is_wake_up()，因为在 AstrBot 中只要注册了监听器，所有进入插件的事件其 event.is_wake 都会被框架置为 True。
        2. @全体成员 (AtAll) 是针对群成员的通告，不应视为指名道姓 @机器人。
        """
        self_id = ""
        if hasattr(event, "get_self_id"):
            try:
                raw_self_id = event.get_self_id()
                if isinstance(raw_self_id, (str, int)):
                    self_id = str(raw_self_id).strip()
            except Exception:
                pass

        # 1. 遍历消息链组件检测 At 和 Reply
        try:
            messages = event.get_messages() or []
            for comp in messages:
                # 显式 @了机器人（比对 QQ/账号 ID 或别名）
                if hasattr(comp, "qq"):
                    qq_str = str(getattr(comp, "qq", "")).strip()
                    if self_id and qq_str == self_id:
                        return True
                if hasattr(comp, "name") and bot_aliases:
                    name_str = str(getattr(comp, "name", "")).strip()
                    if name_str and name_str in bot_aliases:
                        return True

                # 回复了机器人发出的上一条消息
                if hasattr(comp, "sender_id"):
                    sender_id_str = str(getattr(comp, "sender_id", "")).strip()
                    if self_id and sender_id_str == self_id:
                        return True
        except Exception:
            pass

        # 2. 文本中包含 @机器人ID 或 @机器人别名
        raw_text = event.get_message_str() or ""
        if self_id and f"@{self_id}" in raw_text:
            return True

        if bot_aliases:
            for alias in bot_aliases:
                if alias and f"@{alias}" in raw_text:
                    return True

        return False

    @classmethod
    def is_wake_word_message(
        cls,
        event,
        wake_prefixes: Optional[Iterable[str]] = None,
        bot_aliases: Optional[List[str]] = None,
    ) -> Tuple[bool, Optional[str]]:
        """
        判断消息是否使用了自定义唤醒词/唤醒前缀（如 //、/ 等）显式唤醒机器人。
        由于 AstrBot 在 WakingCheckStage 匹配到 wake_prefix 后会将其从 event.message_str 剥离，
        本方法进行多层次精确检测：
        1. 框架剥离前的原始字符串 (event.message_obj.message_str)
        2. 当前事件文本 (event.get_message_str())
        3. 首个组件文本 (event.get_messages())
        4. 底层原始消息 (event.message_obj.raw_message)
        5. AstrBot 框架原生唤醒标记 (event.is_at_or_wake_command)
        """
        prefixes = [str(p).strip() for p in (wake_prefixes or []) if str(p).strip()]
        if not prefixes:
            prefixes = ["//"]

        # 1. 检查 event.message_obj.message_str（框架剥离前的原始文本）
        msg_obj = getattr(event, "message_obj", None)
        orig_msg_str = getattr(msg_obj, "message_str", None)
        if orig_msg_str and isinstance(orig_msg_str, str):
            s = orig_msg_str.strip()
            for p in prefixes:
                if s.startswith(p):
                    return True, p

        # 2. 检查当前 event.get_message_str()
        curr_text = str(event.get_message_str() or "").strip()
        for p in prefixes:
            if curr_text.startswith(p):
                return True, p

        # 3. 检查首个 Plain 文本组件
        try:
            messages = event.get_messages() or []
            if messages:
                first_comp = messages[0]
                comp_text = getattr(first_comp, "text", "") or ""
                if isinstance(comp_text, str) and comp_text.strip():
                    first_stripped = comp_text.strip()
                    for p in prefixes:
                        if first_stripped.startswith(p):
                            return True, p
        except Exception:
            pass

        # 4. 检查底层 raw_message（支持各平台适配器原始结构）
        if msg_obj:
            raw_msg = getattr(msg_obj, "raw_message", None)
            if raw_msg:
                raw_str = ""
                if isinstance(raw_msg, dict):
                    content = raw_msg.get("content", "")
                    if isinstance(content, dict):
                        raw_str = str(content.get("str", "") or "")
                    else:
                        raw_str = str(content or "")
                elif isinstance(raw_msg, str):
                    raw_str = raw_msg
                else:
                    raw_str = str(raw_msg)

                if raw_str:
                    for p in prefixes:
                        if (
                            raw_str.startswith(p)
                            or f"\n{p}" in raw_str
                            or f"\\n{p}" in raw_str
                            or f":{p}" in raw_str
                            or f":\n{p}" in raw_str
                            or f":\\n{p}" in raw_str
                        ):
                            return True, p

        # 5. 检查 AstrBot 框架的原生唤醒标记 is_at_or_wake_command
        # 在群聊中，若框架标记了 is_at_or_wake_command=True，且既非显式@ 也非回复机器人，
        # 则说明必定是命中了 AstrBot 全局配置的 wake_prefix 唤醒词！
        if getattr(event, "is_at_or_wake_command", False) is True:
            is_private = False
            if hasattr(event, "is_private_chat"):
                try:
                    res = event.is_private_chat()
                    if isinstance(res, bool):
                        is_private = res
                except Exception:
                    pass
            if not is_private:
                if not cls.is_explicitly_at_bot(event, bot_aliases):
                    return True, prefixes[0] if prefixes else "//"

        return False, None


