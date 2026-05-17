"""Tx 工厂 — 复刻 @hcengineering/core/src/tx.ts 的 TxFactory 类。

5 个工厂方法（与 TS 1:1 对齐）：
- create_tx_create_doc(_class, space, attributes, object_id?, modified_on?, modified_by?)
- create_tx_update_doc(_class, space, object_id, operations, retrieve?, modified_on?, modified_by?)
- create_tx_remove_doc(_class, space, object_id, modified_on?, modified_by?)
- create_tx_mixin(object_id, object_class, object_space, mixin, attributes, modified_on?, modified_by?)
- create_tx_collection_cud(_class, object_id, space, collection, inner_tx, modified_on?, modified_by?)
  — 注意：TS 实现是「在 inner_tx 上 spread 加 collection/attachedTo/attachedToClass」，不是包外层

ID 生成：secrets.token_hex(12) → 24 字符 hex（与 Huly server 接受的 ObjectId 风格兼容，spike 已验证）
"""

from __future__ import annotations

import secrets
import time
from typing import Any

from .constants import (
    CORE_CLASS_TX_CREATE_DOC,
    CORE_CLASS_TX_MIXIN,
    CORE_CLASS_TX_REMOVE_DOC,
    CORE_CLASS_TX_UPDATE_DOC,
    CORE_SPACE_DERIVED_TX,
    CORE_SPACE_TX,
)


def generate_id() -> str:
    """生成 24 字符 hex id — 与 Huly Ref<T> 兼容（spike 已验证）。"""
    return secrets.token_hex(12)


def _now_ms() -> int:
    return int(time.time() * 1000)


class TxFactory:
    """复刻 TS TxFactory。

    Args:
        account: PersonId / SocialId 字符串（来自 AccountInfo.primary_social_id）
        is_derived: True → space=DerivedTx（server-side 派生 tx），False → space=Tx
    """

    def __init__(self, account: str, *, is_derived: bool = False) -> None:
        self.account = account
        self.is_derived = is_derived
        self._tx_space = CORE_SPACE_DERIVED_TX if is_derived else CORE_SPACE_TX

    # ------------------------------------------------------------------ #
    # TxCreateDoc
    # ------------------------------------------------------------------ #

    def create_tx_create_doc(
        self,
        _class: str,
        space: str,
        attributes: dict[str, Any],
        object_id: str | None = None,
        modified_on: int | None = None,
        modified_by: str | None = None,
    ) -> dict[str, Any]:
        """TS createTxCreateDoc 等价。

        关键字段：
        - _id            tx id
        - _class         core:class:TxCreateDoc
        - space          core:space:Tx（tx 自己的 space）
        - objectId       新 doc id
        - objectClass    doc 的 _class（如 chunter:class:DirectMessage）
        - objectSpace    doc 的目标 space（如 core:space:Space）
        - attributes     doc 字段
        - modifiedBy/On  审计字段
        - createdBy/On   首次创建审计字段（fallback 到 modified*）
        """
        now = modified_on if modified_on is not None else _now_ms()
        modifier = modified_by or self.account
        return {
            "_id": generate_id(),
            "_class": CORE_CLASS_TX_CREATE_DOC,
            "space": self._tx_space,
            "objectId": object_id or generate_id(),
            "objectClass": _class,
            "objectSpace": space,
            "modifiedOn": now,
            "modifiedBy": modifier,
            "createdBy": modifier,
            "createdOn": now,
            "attributes": attributes,
        }

    # ------------------------------------------------------------------ #
    # TxUpdateDoc
    # ------------------------------------------------------------------ #

    def create_tx_update_doc(
        self,
        _class: str,
        space: str,
        object_id: str,
        operations: dict[str, Any],
        retrieve: bool = False,
        modified_on: int | None = None,
        modified_by: str | None = None,
    ) -> dict[str, Any]:
        """TS createTxUpdateDoc 等价。

        operations 支持 TS 的 DocumentUpdate 形态：
        - 直接字段 {field: value} → set
        - $push: {field: value | {$each: [...]}}
        - $pull: {field: value | {$in: [...]}}
        - $inc:  {field: 1}
        - $unset: {field: ""}
        """
        now = modified_on if modified_on is not None else _now_ms()
        return {
            "_id": generate_id(),
            "_class": CORE_CLASS_TX_UPDATE_DOC,
            "space": self._tx_space,
            "modifiedBy": modified_by or self.account,
            "modifiedOn": now,
            "objectId": object_id,
            "objectClass": _class,
            "objectSpace": space,
            "operations": operations,
            "retrieve": retrieve,
        }

    # ------------------------------------------------------------------ #
    # TxRemoveDoc
    # ------------------------------------------------------------------ #

    def create_tx_remove_doc(
        self,
        _class: str,
        space: str,
        object_id: str,
        modified_on: int | None = None,
        modified_by: str | None = None,
    ) -> dict[str, Any]:
        """TS createTxRemoveDoc 等价。"""
        now = modified_on if modified_on is not None else _now_ms()
        return {
            "_id": generate_id(),
            "_class": CORE_CLASS_TX_REMOVE_DOC,
            "space": self._tx_space,
            "modifiedBy": modified_by or self.account,
            "modifiedOn": now,
            "objectId": object_id,
            "objectClass": _class,
            "objectSpace": space,
        }

    # ------------------------------------------------------------------ #
    # TxMixin
    # ------------------------------------------------------------------ #

    def create_tx_mixin(
        self,
        object_id: str,
        object_class: str,
        object_space: str,
        mixin: str,
        attributes: dict[str, Any],
        modified_on: int | None = None,
        modified_by: str | None = None,
    ) -> dict[str, Any]:
        """TS createTxMixin 等价 — 给 Doc 加 mixin 字段。"""
        now = modified_on if modified_on is not None else _now_ms()
        return {
            "_id": generate_id(),
            "_class": CORE_CLASS_TX_MIXIN,
            "space": self._tx_space,
            "modifiedBy": modified_by or self.account,
            "modifiedOn": now,
            "objectId": object_id,
            "objectClass": object_class,
            "objectSpace": object_space,
            "mixin": mixin,
            "attributes": attributes,
        }

    # ------------------------------------------------------------------ #
    # TxCollectionCUD — TS 不创新 _class，只在 inner_tx 上 spread 3 字段
    # ------------------------------------------------------------------ #

    def create_tx_collection_cud(
        self,
        _class: str,
        object_id: str,
        space: str,  # space 在 TS 签名里但实际未读用（兼容性占位）
        collection: str,
        inner_tx: dict[str, Any],
        modified_on: int | None = None,
        modified_by: str | None = None,
    ) -> dict[str, Any]:
        """TS createTxCollectionCUD：

            return {
              ...tx,
              collection,
              attachedTo: objectId,
              attachedToClass: _class,
              modifiedOn: modifiedOn ?? Date.now(),
              modifiedBy: modifiedBy ?? this.account
            }

        Python 等价：浅 copy inner_tx + 加 3 字段 + override modified*。
        """
        del space  # 与 TS 签名对齐但未使用（inner_tx.objectSpace 已是真正的 space）
        now = modified_on if modified_on is not None else _now_ms()
        result = dict(inner_tx)
        result["collection"] = collection
        result["attachedTo"] = object_id
        result["attachedToClass"] = _class
        result["modifiedOn"] = now
        result["modifiedBy"] = modified_by or self.account
        return result
