trigger OpportunityTrigger on Opportunity (before update) {
    for (Opportunity opp : Trigger.new) {
        opp.Discount_Rate__c = 0.20;
    }
}
