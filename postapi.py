import requests
orderPrice=str(0)
orderQuantity=str(10)
exchangeSecurityid=str(4951)
id=str(4951)
cookies = {
    'XSRF-TOKEN': 'ff285c61-270e-4a5f-ae79-16ab469779fc',
    '_aid': 'eyJlbmMiOiJBMTI4R0NNIiwiYWxnIjoiZGlyIn0..VmkDRg0LfvdO_Qvu.IVedELwc9SHKg6cTJCuf9yJdLXlgFyJbXhRK71hjyIb_F1JluLu6AAJeu0jsWFvD9mYOSru6dyUPm2kgnDJQHV0pRP67RvlT3LRXTU54veaCRiR9FCjFTCwLW3lMiBqxyS2uYDXskUKN7LWb0We_stler-1hVW-K6He13t3SnzShlgHqD6UxC8NW3oqgw-tnesR4jqNlg9BgZC-Hx5XhG0yJ8A3fI3gplNLCiLTXJ5q8knxJp2U9uPHjZ_JYnSsHq5tZGcLo4bOwAzbjPl3v76e6ajdooapUXu07YEo9EOd3zcKxXHXjzdJRbrmjZb5SgGsCsQlUKhC7LTQPfAJ4Eqin_phJEcP-7ozc7tCUkxPeaVqJthPfKhj6QKDHA4I7q-I7VsRgBl55Ml_FU8nR4g9hcCBF2lgW2xANBVQLiueaVTeRjf9GOpj8ZJAhxcK4XKzTDeVVUM5EyP4y6pbDQt0Cv2hA08zRvA37Z1rn6moHs9be7D0zim2l1bfDAiUu75A66XQydJHy1n7fqJWLdTvCV1qH9SuHdnytiBR0kJEMNAb86lWXLvhan0Ou3WFOBj2tQhoKiGOU.PYkA0FxAIkrw1VEK00BzdQ',
    '_rid': 'eyJlbmMiOiJBMTI4R0NNIiwiYWxnIjoiZGlyIn0..75pys360kZcVnw2n.lD4o_e1Vd7xXb5JkCsZCTVs1bdYbjACCpn6RC8JZAUHDa8dS17RuuZRcBuCSWjA_LVzzrrrHK9p8E-NcciMSOJMUAFNhGiXTrWaqH9wg5KGtjV-PaQgl_XCCSu5JToj92lWzcbE6UIZMG8x6w5caL1EpaXkh9vbj2p2lLbOECUDk8iQgsrLrBbCLZ46gCusqXWreZ48eK2TCssexnxlGXgSLxW9tijquoh5LHkozQgT98-J4wmR0Ipz4gF2bmYH_ciDL95p35HMzaGmzbq_XcaVd-AAUEnVYjt7d29m3vlr9OcABBZ1mIaKPyNmDeU7y9ee_V-wVQIdAxZu7wBn5oCqEw7QttT_IR1wAzK8ItLxiQO1xjP9WPl2qV6IxNpLxwMphKRPDDFx79UgjkDT12ZRVEWSlIZV2PL9byzD2vkRQDZfVdGWNFeTPcr3cfs6w8bm3Riu3OhQWp8ea1jotzFGHTPWzySd0VuEWSJhR7C0ln-hdClJtFD0NypNxhTeI4s_fTsWiym2AF7dAzaJMSzW1RjLsxKYmKZBhHROWjwqLHEd0YvVmBR9ZAF8qdbwlrP2QNGMYmb3K.uZupLOdKWYcdMIUfh3BkHA',
}

headers = {
    'Connection': 'keep-alive',
    'sec-ch-ua': '" Not;A Brand";v="99", "Google Chrome";v="91", "Chromium";v="91"',
    'X-XSRF-TOKEN': 'ff285c61-270e-4a5f-ae79-16ab469779fc',
    'Request-Owner': '36320',
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.164 Safari/537.36',
    'Host-Session-Id': 'TWpRPS03YzJmMGE3Yi1kOTRlLTRjYTktYjJhYi1kMjFlZGYxMmQ3ZmI=',
    'Content-Type': 'application/json',
    'Accept': 'application/json, text/plain, */*',
    'sec-ch-ua-mobile': '?0',
    'Origin': 'https://tms35.nepsetms.com.np',
    'Sec-Fetch-Site': 'same-origin',
    'Sec-Fetch-Mode': 'cors',
    'Sec-Fetch-Dest': 'empty',
    'Referer': 'https://tms35.nepsetms.com.np/tms/me/memberclientorderentry',
    'Accept-Language': 'en-US,en;q=0.9',
}


data = '{"orderBook":{"orderBookExtensions":[{"orderTypes":{"id":1,"orderTypeCode":"LMT"},"disclosedQuantity":0,"orderValidity":{"id":1,"orderValidityCode":"DAY"},"triggerPrice":0,"orderPrice":'+orderPrice+',"orderQuantity":'+orderQuantity+',"remainingOrderQuantity":10,"marketType":{"id":2,"marketType":"Continuous"}}],"exchange":{"id":1},"dnaConnection":{},"dealer":{},"member":{},"productType":{"id":1,"productCode":"CNC"},"instrumentType":{"id":1,"code":"EQ"},"client":{"activeStatus":"A","id":1974509,"accountType":"CLI","allowedToTrade":"Y","clientMemberCode":"PK479690","clientOrDealer":"C","contactNumber":null,"emailId":null,"notsUniqueClientCode":"201811021236758","clientDealerType":null,"clientGroup":{"activeStatus":"A","id":101,"clientGroupCode":null,"clientGroupName":null},"memberBranch":{"activeStatus":"A","id":1,"branchLocation":null,"branchName":null,"hidden":null,"branchProvince":null,"branchDistrict":null,"branchMunicipality":null,"branchHead":null,"branchPhoneNumber":null},"clientDealerAddressDetails":null,"clientDealerBankDetail":null,"clientDealerIndividual":null,"clientDealerPerTradeLimits":null,"clientDealerProductMappings":null,"clientDealerOrderTypeMappings":null,"clientDealerTradingLimits":null,"clientDepositoryDetail":null,"corporateDetail":null,"corporateOwnershipDetails":null,"displayName":"PUSKAR KAFLE","blockedDate":null,"remarks":null,"parentId":null,"recordType":null,"collateralByEntities":null,"shortSellMode":0,"onlineOrOffline":1,"panNumber":null,"onlineFundTransfer":null,"collateralCalculationMode":1,"isMarginLendingClient":null,"clientRiskType":null},"security":{"id":'+id+',"exchangeSecurityId":'+exchangeSecurityid+',"marketProtectionPercentage":0,"divisor":100,"boardLotQuantity":1,"tickSize":0.1},"accountType":1,"cpMemberId":0,"buyOrSell":1},"orderPlacedBy":2,"exchangeOrderId":null}'

# response = requests.post('https://tms35.nepsetms.com.np/tmsapi/orderApi/orderbook-v2/', headers=headers, cookies=cookies, data=data)

print(data)
# print(response.status_code)