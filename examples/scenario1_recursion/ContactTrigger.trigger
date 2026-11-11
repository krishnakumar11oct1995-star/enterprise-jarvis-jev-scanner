trigger ContactTrigger on Contact (after update) {
    ContactService.handleContactUpdate(Trigger.new);
}
