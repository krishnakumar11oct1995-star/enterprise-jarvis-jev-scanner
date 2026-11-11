trigger AccountTrigger on Account (after update) {
    AccountService.handleAccountUpdate(Trigger.new);
}
