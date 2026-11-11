public class AccountService {
    public static void handleAccountUpdate(List<Account> accounts) {
        List<Contact> contacts = [SELECT Id, AccountId FROM Contact WHERE AccountId IN :accounts];
        update contacts;
    }
}
