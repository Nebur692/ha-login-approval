from unittest.mock import AsyncMock, patch

from app.approval_flow import ApprovalOutcome, LoginContext, run_approval

CONTEXT = LoginContext(ip="203.0.113.5", browser_description="Chrome")


async def test_no_targets():
    with patch("app.approval_flow.zitadel_client.get_user_ha_targets", AsyncMock(return_value=[])):
        outcome = await run_approval("u1", "req-1", CONTEXT)
    assert outcome == ApprovalOutcome.NO_TARGETS


async def test_approved():
    with patch("app.approval_flow.zitadel_client.get_user_ha_targets", AsyncMock(return_value=["mobile_app_x"])), \
         patch("app.approval_flow.ha_client.get_ha_language", AsyncMock(return_value="en")), \
         patch("app.approval_flow.ha_client.send_approval_notification", AsyncMock()), \
         patch("app.approval_flow.ha_client.wait_for_action", AsyncMock(return_value=True)):
        outcome = await run_approval("u1", "req-1", CONTEXT)
    assert outcome == ApprovalOutcome.APPROVED


async def test_all_sends_failing_short_circuits_without_waiting():
    """If every target's send raised, there's nobody left to respond —
    shouldn't burn the full approval_timeout_seconds waiting for nothing."""
    wait_mock = AsyncMock(return_value=None)
    with patch("app.approval_flow.zitadel_client.get_user_ha_targets",
               AsyncMock(return_value=["mobile_app_x", "mobile_app_y"])), \
         patch("app.approval_flow.ha_client.get_ha_language", AsyncMock(return_value="en")), \
         patch("app.approval_flow.ha_client.send_approval_notification", AsyncMock(side_effect=Exception("boom"))), \
         patch("app.approval_flow.ha_client.wait_for_action", wait_mock):
        outcome = await run_approval("u1", "req-1", CONTEXT)
    assert outcome == ApprovalOutcome.SEND_FAILED
    wait_mock.assert_not_called()


async def test_partial_send_failure_still_waits_for_the_others():
    """Only one of two targets failing to send is not SEND_FAILED — the
    other one might still get a response."""
    send_mock = AsyncMock(side_effect=[Exception("boom"), None])
    with patch("app.approval_flow.zitadel_client.get_user_ha_targets",
               AsyncMock(return_value=["mobile_app_x", "mobile_app_y"])), \
         patch("app.approval_flow.ha_client.get_ha_language", AsyncMock(return_value="en")), \
         patch("app.approval_flow.ha_client.send_approval_notification", send_mock), \
         patch("app.approval_flow.ha_client.wait_for_action", AsyncMock(return_value=True)):
        outcome = await run_approval("u1", "req-1", CONTEXT)
    assert outcome == ApprovalOutcome.APPROVED


async def test_rejected():
    with patch("app.approval_flow.zitadel_client.get_user_ha_targets", AsyncMock(return_value=["mobile_app_x"])), \
         patch("app.approval_flow.ha_client.get_ha_language", AsyncMock(return_value="en")), \
         patch("app.approval_flow.ha_client.send_approval_notification", AsyncMock()), \
         patch("app.approval_flow.ha_client.wait_for_action", AsyncMock(return_value=False)):
        outcome = await run_approval("u1", "req-1", CONTEXT)
    assert outcome == ApprovalOutcome.REJECTED


async def test_timeout():
    with patch("app.approval_flow.zitadel_client.get_user_ha_targets", AsyncMock(return_value=["mobile_app_x"])), \
         patch("app.approval_flow.ha_client.get_ha_language", AsyncMock(return_value="en")), \
         patch("app.approval_flow.ha_client.send_approval_notification", AsyncMock()), \
         patch("app.approval_flow.ha_client.wait_for_action", AsyncMock(return_value=None)):
        outcome = await run_approval("u1", "req-1", CONTEXT)
    assert outcome == ApprovalOutcome.TIMEOUT
