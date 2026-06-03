import os
import re
from typing import AsyncGenerator

import httpx

from ling_chat.core.logger import logger
from ling_chat.core.TTS.base_adapter import TTSBaseAdapter


class GPTSoVITSAdapter(TTSBaseAdapter):
    def __init__(
        self,
        ref_audio_path: str,
        prompt_text: str = "",
        prompt_lang: str = "ja",
        audio_format: str = "wav",
        text_lang: str = "ja",
        parallel_infer: bool = False,
        api_url: str | None = None,
        anti_clipping: bool = True,
        speed_factor: float = 1.0,
        top_k: int = 15,
        top_p: float = 1.0,
        temperature: float = 1.0,
    ):
        self.anti_clipping = anti_clipping
        if api_url:
            self.api_url = api_url.rstrip("/")
        else:
            api_url_env = os.environ.get("GPT_SOVITS_API_URL", "http://127.0.0.1:9880")
            self.api_url = api_url_env.rstrip("/")

        # 支持的语言（v2及以上）：
        # auto 多语种自动识别切分
        # en	英语
        # zh	中英混合识别
        # ja	日英混合识别
        # yue	粤英混合识别
        # ko	韩英混合识别
        # all_zh	全部按中文识别
        # all_ja	全部按日文识别
        # all_yue	全部按粤语识别
        # all_ko	全部按韩文识别
        # auto_yue	粤语多语种自动识别切分
        self.params: dict[str, str | int | float] = {
            "ref_audio_path": ref_audio_path,
            "prompt_text": prompt_text,
            "prompt_lang": prompt_lang,
            "text_lang": text_lang,
            "media_type": audio_format,  # 支持wav,raw,ogg,aac
            "speed_factor": speed_factor,
            "text_split_method": "cut5",
            "top_k": top_k,
            "top_p": top_p,
            "temperature": temperature,
            "parallel_infer": parallel_infer,
            "text": "",
        }

    async def generate_voice(self, text: str) -> bytes:
        params = dict(self.params)
        params["text"] = text
        logger.debug(f"发送到GPT-SoVITS的json: {params}")

        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.api_url + "/tts", json=params, timeout=30.0
            )
            if response.status_code != 200:
                raise RuntimeError(f"TTS请求失败: {response.text}")
            return response.content

    def _split_text(self, text: str) -> list[str]:
        """按语义标点切分文本，不做硬性数字截断"""
        if not text:
            return []

        # 一级切分（强）：句末标点
        strong = re.split(r"(?<=[。！？；])", text)
        chunks: list[str] = []
        for seg in strong:
            if not seg:
                continue
            # 二级切分（弱）：从句内标点，但保留最小长度
            if len(seg) > 20:
                sub = re.split(r"(?<=[、，,])", seg)
                chunks.extend(s for s in sub if s)
            else:
                chunks.append(seg)
        return [c for c in chunks if c]

    async def generate_voice_stream(
        self, text: str
    ) -> AsyncGenerator[bytes, None]:
        """流式生成语音：逐 chunk 调用 GSV API，yield wav bytes"""
        chunks = self._split_text(text)

        for chunk in chunks:
            params = dict(self.params)
            # 每个 chunk 前加"，，"防吞音（默认开启，可关闭）
            if self.anti_clipping:
                params["text"] = "，，" + chunk
            else:
                params["text"] = chunk

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.api_url + "/tts", json=params, timeout=30.0
                )
                if response.status_code != 200:
                    logger.warning(f"TTS chunk failed: {response.text}")
                    continue
                yield response.content

    async def set_model(self, gpt_model_path: str, sovits_model_path: str) -> bool:
        """
        设置GPT和SoVITS模型

        :param gpt_model_path: GPT模型的路径
        :param sovits_model_path: SoVITS模型的路径
        :return: 是否设置成功
        """
        try:
            # 检查模型文件是否存在
            if not os.path.exists(gpt_model_path):
                logger.error(f"GPT模型文件不存在: {gpt_model_path}")
                raise FileNotFoundError(f"GPT模型文件不存在: {gpt_model_path}")

            if not os.path.exists(sovits_model_path):
                logger.error(f"SoVITS模型文件不存在: {sovits_model_path}")
                raise FileNotFoundError(f"SoVITS模型文件不存在: {sovits_model_path}")

            # 检查模型文件扩展名
            if not gpt_model_path.endswith(".ckpt"):
                logger.error(f"GPT模型文件扩展名必须为.ckpt: {gpt_model_path}")
                raise ValueError(f"GPT模型文件扩展名必须为.ckpt: {gpt_model_path}")

            if not sovits_model_path.endswith(".pth"):
                logger.error(f"SoVITS模型文件扩展名必须为.pth: {sovits_model_path}")
                raise ValueError(f"SoVITS模型文件扩展名必须为.pth: {sovits_model_path}")

            async with httpx.AsyncClient() as client:
                # 设置GPT模型
                if gpt_model_path:
                    gpt_url = self.api_url + "/set_gpt_weights"
                    response = await client.get(
                        gpt_url, params={"weights_path": gpt_model_path}, timeout=30.0
                    )
                    if response.status_code != 200:
                        logger.error(f"GPT模型设置失败: {response.text}")
                        return False
                    logger.debug(f"GPT模型设置成功: {gpt_model_path}")

                # 设置SoVITS模型
                if sovits_model_path:
                    sovits_url = self.api_url + "/set_sovits_weights"
                    response = await client.get(
                        sovits_url,
                        params={"weights_path": sovits_model_path},
                        timeout=30.0,
                    )
                    if response.status_code != 200:
                        logger.error(f"SoVITS模型设置失败: {response.text}")
                        return False
                    logger.debug(f"SoVITS模型设置成功: {sovits_model_path}")

                return True
        except Exception as e:
            logger.error(f"模型设置过程中出现异常: {str(e)}")
            return False

    def get_params(self):
        return self.params
