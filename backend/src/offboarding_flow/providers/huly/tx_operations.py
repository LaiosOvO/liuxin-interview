"""TxOperations — 复刻 @hcengineering/core/src/operations.ts 的 TxOperations 类。

提供与 sidecar PlatformClient 同接口的高阶 CRUD 方法：
- create_doc / update_doc / remove_doc
- add_collection / update_collection / remove_collection
- create_mixin / update_mixin

每个方法内部 = TxFactory 合 Tx 对象 → HulyRestClient.tx() 提交。

设计差异 vs TS：
- TS 用 hierarchy.isDerived(class, AttachedDoc) 校验「createDoc 不能创 AttachedDoc」
  → Python 不做（少 load model 一步；让 server 自己 reject）
- TS 用 hierarchy.findDomain(class) === DOMAIN_MODEL 校验 model space
  → Python 不做（同上）
- 校验少了换来「不需要 load_model」— 显著简化（model 解 ~1MB+ TS hierarchy JSON 不值）
"""

from __future__ import annotations

import logging
from typing import Any

from .rest_client import HulyRestClient
from .tx_factory import TxFactory

logger = logging.getLogger(__name__)


class TxOperations:
    """TxOperations facade — 串 TxFactory + HulyRestClient.tx 提供高阶 API。

    用法:
        client = HulyRestClient(...)
        await client.select_workspace(...)
        account = await client.get_account()
        ops = TxOperations(client, account.primary_social_id)
        doc_id = await ops.create_doc(
            'chunter:class:DirectMessage',
            'core:space:Space',
            {'name': '', 'description': '', 'private': True, 'archived': False,
             'members': [bot_uuid, target_uuid]},
        )
    """

    def __init__(
        self,
        client: HulyRestClient,
        user: str,
        *,
        is_derived: bool = False,
    ) -> None:
        self.client = client
        self.user = user
        self.tx_factory = TxFactory(user, is_derived=is_derived)

    # ------------------------------------------------------------------ #
    # 单 Doc 操作
    # ------------------------------------------------------------------ #

    async def create_doc(
        self,
        _class: str,
        space: str,
        attributes: dict[str, Any],
        object_id: str | None = None,
    ) -> str:
        """createDoc → 返回新创 doc 的 objectId。"""
        tx = self.tx_factory.create_tx_create_doc(_class, space, attributes, object_id)
        await self.client.tx(tx)
        return str(tx["objectId"])

    async def update_doc(
        self,
        _class: str,
        space: str,
        object_id: str,
        operations: dict[str, Any],
        retrieve: bool = False,
    ) -> Any:
        """updateDoc — operations 支持 $push/$pull/$inc/$unset。"""
        tx = self.tx_factory.create_tx_update_doc(_class, space, object_id, operations, retrieve)
        return await self.client.tx(tx)

    async def remove_doc(self, _class: str, space: str, object_id: str) -> Any:
        """removeDoc。"""
        tx = self.tx_factory.create_tx_remove_doc(_class, space, object_id)
        return await self.client.tx(tx)

    # ------------------------------------------------------------------ #
    # Collection 操作 — 内部是 inner Tx 加 3 字段（attachedTo/attachedToClass/collection）
    # ------------------------------------------------------------------ #

    async def add_collection(
        self,
        _class: str,
        space: str,
        attached_to: str,
        attached_to_class: str,
        collection: str,
        attributes: dict[str, Any],
        object_id: str | None = None,
    ) -> str:
        """addCollection → 返回新 AttachedDoc 的 objectId。

        TS 等价（operations.ts:121-143）：
            const tx = txFactory.createTxCollectionCUD(
              attachedToClass, attachedTo, space, collection,
              txFactory.createTxCreateDoc(_class, space, attributes, id),
            )
            await this.tx(tx)
            return tx.objectId
        """
        inner = self.tx_factory.create_tx_create_doc(_class, space, attributes, object_id)
        tx = self.tx_factory.create_tx_collection_cud(
            attached_to_class, attached_to, space, collection, inner
        )
        await self.client.tx(tx)
        return str(tx["objectId"])

    async def update_collection(
        self,
        _class: str,
        space: str,
        object_id: str,
        attached_to: str,
        attached_to_class: str,
        collection: str,
        operations: dict[str, Any],
        retrieve: bool = False,
    ) -> str:
        """updateCollection → 返回 attached_to id（与 TS 一致）。"""
        inner = self.tx_factory.create_tx_update_doc(_class, space, object_id, operations, retrieve)
        tx = self.tx_factory.create_tx_collection_cud(
            attached_to_class, attached_to, space, collection, inner
        )
        await self.client.tx(tx)
        return attached_to

    async def remove_collection(
        self,
        _class: str,
        space: str,
        object_id: str,
        attached_to: str,
        attached_to_class: str,
        collection: str,
    ) -> str:
        """removeCollection → 返回 attached_to id。"""
        inner = self.tx_factory.create_tx_remove_doc(_class, space, object_id)
        tx = self.tx_factory.create_tx_collection_cud(
            attached_to_class, attached_to, space, collection, inner
        )
        await self.client.tx(tx)
        return attached_to

    # ------------------------------------------------------------------ #
    # Mixin 操作
    # ------------------------------------------------------------------ #

    async def create_mixin(
        self,
        object_id: str,
        object_class: str,
        object_space: str,
        mixin: str,
        attributes: dict[str, Any],
    ) -> Any:
        tx = self.tx_factory.create_tx_mixin(
            object_id, object_class, object_space, mixin, attributes
        )
        return await self.client.tx(tx)

    async def update_mixin(
        self,
        object_id: str,
        object_class: str,
        object_space: str,
        mixin: str,
        attributes: dict[str, Any],
    ) -> Any:
        # TS 实现里 create/update 共用同一 tx — Python 同样
        return await self.create_mixin(object_id, object_class, object_space, mixin, attributes)
