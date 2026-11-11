public class ContactService {
    public static void handleContactUpdate(List<Contact> contacts) {
        List<Account> accounts = [SELECT Id FROM Account WHERE Id IN :contacts];
        update accounts;
    }
}
